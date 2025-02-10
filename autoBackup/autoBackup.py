from truenas_api_client import Client
import requests
import dotenv
import json
import os

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(env_path):
    dotenv.load_dotenv(dotenv_path = env_path)

class TrueNASAPIClient:
    def __init__(self, host, api_key):
        self.base_url = base_url = "http://%s/api/v2.0" % host
        self.headers = {
            "Authorization": "Bearer " + api_key
        }

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
    
    def get_replication_naming_schemas(self):
        return self.base_get("/replication/list_naming_schemas")
    
    def get_jobs(self):
        return self.base_get("/core/get_jobs")
    
    def get_replication_jobs(self):
        return [i for i in self.get_jobs() if i["method"] == "replication.run"]
    
    def get_running_replication_jobs(self):
        return [i for i in self.get_jobs() if i["method"] == "replication.run" and i["progress"]["percent"] != 100 and not i["state"] == "FAILED"]
    
    def get_running_jobs(self):
        return [i for i in self.get_jobs() if i["progress"]["percent"] != 100]
    
    def get_replication_tasks(self):
        return self.base_get("/replication")

if __name__ == "__main__":
    truenas = TrueNASAPIClient(host = os.environ["SLAVE_HOST"], api_key = os.environ["SLAVE_KEY"])
    print(json.dumps(truenas.get_replication_tasks(), indent = 4))