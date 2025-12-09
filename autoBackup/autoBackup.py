import truenas_api_client
import subprocess
import datetime
import requests
import logging
import pickle
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

class TrueNASWebsocketsClient(truenas_api_client.JSONRPCClient):
    """Using API keys with a self-signed certificate automatically invalidates them now? So
    we have to use less secure username and password authentication instead....
    And attempting to set up a reverse proxy with HAProxy apparently means then the sockets API
    doesn't work... (see bottom)

    Also, despite what the documentation says, it seems the websockets API doesn't like calls
    over a long time with the same authentication, so we make a new session and re-authenticate
    every time we poll the jobs. Yes this is directly contradicting what the documentation tells us
    to do. Therefore, we serialize the dictionary of currently running jobs so we can make lots of new
    instances of this object.

    The HTTP API is better in every way, but apparently it will be removed in a future version of TrueNAS
    (25.10?) hence we have this instead.

    This implementation of the websockets API only works in 25.04 and onwards.
    """
    def __init__(self, host, username, password, replication_task_names = None, *args, **kwargs):
        super().__init__(uri = "ws://%s/api/current" % host, *args, **kwargs)
        self.host = host
        self.username = username
        self.password = password

        if replication_task_names is None:
            self.replication_task_names = []
        else:
            self.replication_task_names = replication_task_names

    def __enter__(self):
        o = super().__enter__()
        # We are forced to use username/password instead of API keys if we're using self-certified certificates
        auth = self.call("auth.login", self.username, self.password)
        return o
    
    def __exit__(self, *args, **kwargs):
        super().__exit__(*args, **kwargs)
        # logging.info("%s Websocket disconnected" % self.host)
    
    def _get_job_serialized_name(self, job_type):
        return os.path.join(os.path.dirname(__file__), ".%s_%s_jobs.pickle" % (self.host, job_type))
    
    def _get_serialized_jobs(self, job_type):
        if os.path.exists(self._get_job_serialized_name(job_type)):
            with open(self._get_job_serialized_name(job_type), "rb") as f:
                return pickle.load(f)
        else:
            return {}
        
    def _set_serialized_jobs(self, jobs, job_name):
        with open(self._get_job_serialized_name(job_name), "wb") as f:
            pickle.dump(jobs, f)
    
    def get_replication_tasks(self):
        return list(filter(lambda a: a["name"] in self.replication_task_names, self.call("replication.query")))
    
    def run_replication_task(self, task_id):
        return self.call("replication.run", task_id)
    
    @staticmethod
    def is_ready(host, username, password, *args, **kwargs):
        try:
            with truenas_api_client.JSONRPCClient(uri = "ws://%s/api/current" % host, *args, **kwargs) as c:
                c.call("auth.login", username, password)
                return c.call("system.ready")
        except OSError:
            raise ConnectionError("No route to host")
    
    def shutdown(self):
        return self.call("system.shutdown", "Automatic autoBackup shutdown")
    
    def run_all_replication_tasks(self):
        running_replication_jobs = self._get_serialized_jobs("replication")

        for task in self.get_replication_tasks():
            job_id = self.run_replication_task(task["id"])
            running_replication_jobs[job_id] = task["name"]
            logging.info("Started replication task '%s' on '%s' with job id %d" % (task["name"], self.host, job_id))

        self._set_serialized_jobs(running_replication_jobs, "replication")

    def scrub_pools(self, pools):
        running_jobs = self._get_serialized_jobs("scrub")

        for pool_name in pools:
            job_id = self.call("pool.scrub.scrub", pool_name)
            running_jobs[job_id] = pool_name
            logging.info("Started scrub job on pool '%s' on host '%s' with job id %d" % (pool_name, self.host, job_id))

        self._set_serialized_jobs(running_jobs, "scrub")

    def get_jobs(self):
        return self.call("core.get_jobs")
    
    def get_state_of_replication_jobs(self):
        return self.get_state_of_jobs("replication")

    def get_state_of_jobs(self, job_type):
        running_jobs = self._get_serialized_jobs(job_type)
        all_complete = True
        for job in self.get_jobs():
            if job["id"] in running_jobs.keys():
                if job["state"] == "RUNNING":
                    all_complete = False
                logging.info("%s job '%s' on '%s' is currently '%s' (%d%%)" % (
                    job_type, running_jobs[job["id"]], self.host, job["state"], job["progress"]["percent"]
                ))

        if all_complete:
            if os.path.exists(self._get_job_serialized_name(job_type)):
                os.remove(self._get_job_serialized_name(job_type))
                logging.info("All %s jobs on '%s' completed" % (job_type, self.host))
            else:
                logging.info("There were no %s jobs on '%s'. Perhaps they already all finished." % (job_type, self.host))
        return all_complete

class TrueNASAPIClient:
    """Class for the REST HTTP API, which sadly will be removed soon :c
    """
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
        verbose = False,
        message = message
    )

def wait_for_slave(slave):
    """Wait for a TrueNAS REST HTTP Client to be ready

    Args:
        slave (TrueNASAPIClient): A TrueNAS REST client
    """
    while True:
        time.sleep(int(os.environ["POLLING_RATE"]))
        try:
            ready = slave.is_ready()
            logging.info("Slave is ready: " + str(ready))
            if not ready:
                continue
        except (requests.exceptions.ConnectionError, truenas_api_client.exc.ClientException):
            logging.info("'%s' hasn't booted, waiting for %d more seconds" % (slave.host, int(os.environ["POLLING_RATE"])))
        else:
            break
    logging.info("Slave TrueNAS has booted and is ready for API requests")

def wait_for_sockets_slave():
    """Wait for the slave's websockets API to be ready
    """
    while True:
        time.sleep(int(os.environ["POLLING_RATE"]))
        try:
            ready = TrueNASWebsocketsClient.is_ready(
                host = os.environ["SLAVE_HOST"], 
                username = os.environ["SLAVE_USERNAME"],
                password = os.environ["SLAVE_PASSWORD"]
            )
            logging.info("Slave is ready: " + str(ready))
            if not ready:
                continue
        except ConnectionError:
            logging.info("'%s' hasn't booted, waiting for %d more seconds" % (os.environ["SLAVE_HOST"], int(os.environ["POLLING_RATE"])))
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
    start_time = datetime.datetime.now()
    subprocess.run(["rm", "-f", os.path.join(os.path.dirname(__file__), "*_replication_jobs.pickle")])

    if os.environ["MASTER_REPLICATION_TASKS"] != "":
        master_tasks = os.environ["MASTER_REPLICATION_TASKS"].split(",")
    else:
        master_tasks = []
    if os.environ["SLAVE_REPLICATION_TASKS"] != "":
        slave_tasks = os.environ["SLAVE_REPLICATION_TASKS"].split(",")
    else:
        slave_tasks = []

    logging.info("\n\nBegan autoBackup procedure")
    m = get_mqtt()
    logging.info("Slave plug '%s' is currently %s" % (m.friendlyname, m.switch_power))
    if m.switch_power == "ON":
        was_already_on = True
    else:
        was_already_on = False
        get_mqtt("ON")
        logging.info("Turned on the slave plug. Now waiting for it to boot")
        # wait_for_slave(slave)
        wait_for_sockets_slave()

    with (TrueNASWebsocketsClient(
            host = os.environ["SLAVE_HOST"], 
            username = os.environ["SLAVE_USERNAME"],
            password = os.environ["SLAVE_PASSWORD"],
            replication_task_names = slave_tasks
        ) as slave, TrueNASWebsocketsClient(
            host = os.environ["MASTER_HOST"], 
            username = os.environ["MASTER_USERNAME"],
            password = os.environ["MASTER_PASSWORD"],
            replication_task_names = master_tasks
        ) as master
    ):
        master.run_all_replication_tasks()
        slave.run_all_replication_tasks()
        
    while True:
        with (TrueNASWebsocketsClient(
                host = os.environ["SLAVE_HOST"], 
                username = os.environ["SLAVE_USERNAME"],
                password = os.environ["SLAVE_PASSWORD"],
                replication_task_names = slave_tasks
            ) as slave, TrueNASWebsocketsClient(
                host = os.environ["MASTER_HOST"], 
                username = os.environ["MASTER_USERNAME"],
                password = os.environ["MASTER_PASSWORD"],
                replication_task_names = master_tasks
            ) as master
        ):
            if check_if_all_complete([master, slave]):
                break

        logging.info("Slave plug '%s' is using %dw of power" % (os.environ["SLAVE_PLUG_FRIENDLYNAME"], get_mqtt().switch_energy['Power']))
        time.sleep(int(os.environ["POLLING_RATE"]))

    logging.info("All replication jobs on all hosts complete")

    if was_already_on:
        logging.info("The slave TrueNAS was turned on not by us, so stopping here")
    else:
        logging.info("The slave TrueNAS was turned on by us, so starting the shutdown procedure")
        with TrueNASWebsocketsClient(
            host = os.environ["SLAVE_HOST"], 
            username = os.environ["SLAVE_USERNAME"],
            password = os.environ["SLAVE_PASSWORD"],
            replication_task_names = slave_tasks
        ) as slave:
            slave.shutdown()
            # logging.info(json.dumps(slave.shutdown(), indent = 4))

        # wait until the slave TrueNAS is using 0w of power, which implies it has finished shutting down,
        # then turn off the power to it
        wait_till_idle_power()
        get_mqtt("OFF")
        logging.info("Turned off the slave's plug")

    logging.info("autoBackup backup procedure completed. Took %s" % str(datetime.datetime.now() - start_time))

if __name__ == "__main__":
    main()


    
