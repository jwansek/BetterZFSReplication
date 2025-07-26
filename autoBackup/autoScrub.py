import subprocess
from autoBackup import TrueNASWebsocketsClient, get_mqtt, wait_for_sockets_slave, wait_till_idle_power
import datetime
import logging
import time
import json
import os

def main():
    start_time = datetime.datetime.now()
    subprocess.run(["rm", "-f", os.path.join(os.path.dirname(__file__), "*_scrub_jobs.pickle")])

    if os.environ["SLAVE_SCRUB_POOLS"] != "":
        scrub_pools = os.environ["SLAVE_SCRUB_POOLS"].split(",")
    else:
        scrub_pools = []

    logging.info("Began autoScrub scrub procedure")
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

    with TrueNASWebsocketsClient(
        host = os.environ["SLAVE_HOST"], 
        username = os.environ["SLAVE_USERNAME"],
        password = os.environ["SLAVE_PASSWORD"]
    ) as slave:
        slave.scrub_pools(scrub_pools)

    while True:
        with TrueNASWebsocketsClient(
            host = os.environ["SLAVE_HOST"], 
            username = os.environ["SLAVE_USERNAME"],
            password = os.environ["SLAVE_PASSWORD"]
        ) as slave:
            if slave.get_state_of_jobs("scrub"):
                break

        logging.info("Slave plug '%s' is using %dw of power" % (os.environ["SLAVE_PLUG_FRIENDLYNAME"], get_mqtt().switch_energy['Power']))
        time.sleep(int(os.environ["POLLING_RATE"]))

    logging.info("All scrub jobs on all hosts complete")

    if was_already_on:
        logging.info("The slave TrueNAS was turned on not by us, so stopping here")
    else:
        logging.info("The slave TrueNAS was turned on by us, so starting the shutdown procedure")
        with TrueNASWebsocketsClient(
            host = os.environ["SLAVE_HOST"], 
            username = os.environ["SLAVE_USERNAME"],
            password = os.environ["SLAVE_PASSWORD"],
        ) as slave:
            logging.info(json.dumps(slave.shutdown(), indent = 4))

        # wait until the slave TrueNAS is using 0w of power, which implies it has finished shutting down,
        # then turn off the power to it
        wait_till_idle_power()
        get_mqtt("OFF")
        logging.info("Turned off the slave's plug")

    logging.info("autoScrub scrub procedure completed. Took %s\n\n" % str(datetime.datetime.now() - start_time))

if __name__ == "__main__":
    main()