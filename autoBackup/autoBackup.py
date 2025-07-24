import truenas_api_client
import requests
import logging
import dotenv
import json
import time
import sys
import os

sys.path.insert(1, os.path.join(os.path.dirname(__file__), "TasmotaCLI"))
import tasmotaMQTTClient

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    dotenv.load_dotenv(dotenv_path = env_path)

logging.basicConfig( 
    format = "[%(asctime)s]\t%(message)s", 
    level = logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "logs", "backup.log")),
        logging.StreamHandler()
    ]
)

class TrueNASAPIClient:
    def __init__(self, host, api_key, replication_task_names = None):
        self.host = host
        self.base_url = "http://%s/api/v2.0" % host
        self.headers = {
            "Authorization": "Bearer " + api_key
        }
        if replication_task_names is None:
            self.replication_task_names = []
        else:
            self.replication_task_names = replication_task_names

        self.running_replication_jobs = {}

    @staticmethod
    def filter_running_jobs(jobs):
        return list(filter(
            lambda i: i["progress"]["percent"] != 100 and not i["state"] == "FAILED",
            jobs
        ))
        
    def base_get(self, endpoint, payload = None):
        if payload is None:
            payload = {}

        if not endpoint.startswith("/"):
            endpoint = "/" + endpoint

        req = requests.get(self.base_url + endpoint, headers = self.headers, data = payload)
        if not req.status_code == 200:
            raise ConnectionError("API call failed (%d): '%s'" % (req.status_code, req.content.decode()))
        return req.json()
    
    def get_websocket_connections(self):
        return self.base_get("/core/sessions")
    
    def get_jobs(self):
        return self.base_get("/core/get_jobs")
    
    def get_replication_tasks(self):
        return list(filter(lambda a: a["name"] in self.replication_task_names, self.base_get("/replication")))
    
    def run_replication_task(self, task_id):
        req = requests.post(self.base_url + "/replication/id/%d/run" % task_id, headers = self.headers)
        if not req.status_code == 200:
            raise ConnectionError("API call failed (%d): '%s'" % (req.status_code, req.content.decode()))
        return req.json()
    
    def is_ready(self):
        return self.base_get("/system/ready")
    
    def shutdown(self):
        req = requests.post(self.base_url + "/system/shutdown", headers = self.headers, json = {"reason": "Automatic autoBackup shutdown"})
        if not req.status_code == 200:
            raise ConnectionError("API call failed (%d): '%s'" % (req.status_code, req.content.decode()))
        return req.json()

    def run_all_replication_tasks(self):
        for task in self.get_replication_tasks():
            job_id = self.run_replication_task(task["id"])
            self.running_replication_jobs[job_id] = task["name"]
            logging.info("Started replication task '%s' on '%s' with job id %d" % (task["name"], self.host, job_id))

    def get_state_of_replication_jobs(self):
        all_complete = True
        for job in self.get_jobs():
            if job["id"] in self.running_replication_jobs.keys():
                if job["state"] == "RUNNING":
                    all_complete = False
                logging.info("Replication job '%s' on '%s' is currently '%s' (%d%%)" % (
                    self.running_replication_jobs[job["id"]], self.host, job["state"], job["progress"]["percent"]
                ))

        if all_complete:
            self.running_replication_jobs = {}
            logging.info("No more running replication jobs on '%s'" % self.host)
        return all_complete

def check_if_all_complete(truenasclients):
    logging.info("Slave plug '%s' is using %dw of power" % (os.environ["SLAVE_PLUG_FRIENDLYNAME"], get_mqtt().switch_energy['Power']))
    all_complete = True
    for truenas in truenasclients:
        if not truenas.get_state_of_replication_jobs():
            all_complete = False
    return all_complete

def get_mqtt(message = None):
    return tasmotaMQTTClient.MQTTClient(
        host = os.environ["MQTT_HOST"],
        username = os.environ["MQTT_USER"],
        password = os.environ["MQTT_PASSWORD"],
        friendlyname = os.environ["SLAVE_PLUG_FRIENDLYNAME"],
        message = message
    )

def wait_for_slave(slave):
    while True:
        time.sleep(int(os.environ["POLLING_RATE"]))
        try:
            logging.info("Slave is ready: " + str(slave.is_ready()))
        except requests.exceptions.ConnectionError:
            logging.info("'%s' hasn't booted, waiting for %d more seconds" % (slave.host, int(os.environ["POLLING_RATE"])))
        else:
            break
    logging.info("Slave TrueNAS has booted and is ready for API requests")

def wait_till_idle_power():
    while True:
        p = get_mqtt().switch_energy['Power']
        logging.info("'%s' plug is using %dw of power" % (os.environ["SLAVE_PLUG_FRIENDLYNAME"], p))
        if p == 0:
            break

def main():
    if os.environ["MASTER_REPLICATION_TASKS"] != "":
        tasks = os.environ["MASTER_REPLICATION_TASKS"].split(",")
    else:
        tasks = []
    master = TrueNASAPIClient(
        host = os.environ["MASTER_HOST"], 
        api_key = os.environ["MASTER_KEY"], 
        replication_task_names = tasks
    )
    if os.environ["SLAVE_REPLICATION_TASKS"] != "":
        tasks = os.environ["SLAVE_REPLICATION_TASKS"].split(",")
    else:
        tasks = []
    slave = TrueNASAPIClient(
        host = os.environ["SLAVE_HOST"], 
        api_key = os.environ["SLAVE_KEY"], 
        replication_task_names = tasks
    )

    logging.info("Began autoBackup procedure")
    m = get_mqtt()
    logging.info("Slave plug '%s' is currently %s" % (m.friendlyname, m.switch_power))
    if m.switch_power == "ON":
        was_already_on = True
    else:
        was_already_on = False
        get_mqtt("ON")
        logging.info("Turned on the slave plug. Now waiting for it to boot")
        wait_for_slave(slave)

    master.run_all_replication_tasks()
    slave.run_all_replication_tasks()
    # while (not master.get_state_of_replication_jobs()) or (not slave.get_state_of_replication_jobs()):
    while not check_if_all_complete([master, slave]):
        time.sleep(int(os.environ["POLLING_RATE"]))
    logging.info("All replication jobs on all hosts complete")

    if was_already_on:
        logging.info("The slave TrueNAS was turned on not by us, so stopping here")
    else:
        logging.info("The slave TrueNAS was turned on by us, so starting the shutdown procedure")
        logging.info(json.dumps(slave.shutdown(), indent = 4))

        # wait until the slave TrueNAS is using 0w of power, which implies it has finished shutting down,
        # then turn off the power to it
        wait_till_idle_power()
        get_mqtt("OFF")
        logging.info("Turned off the slave's plug")

    logging.info("autoBackup procedure completed\n\n")

if __name__ == "__main__":
    # main()
    
    with truenas_api_client.Client(uri="ws://%s/api/current" % os.environ["MASTER_HOST"]) as c:
        c.call("auth.login_with_api_key", os.environ["MASTER_KEY"])
