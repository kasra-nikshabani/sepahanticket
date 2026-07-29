from locust import HttpUser, task, between

MATCH_ID = 5  # <-- شناسه مسابقه خودت را بگذار


class AnonymousReader(HttpUser):
    wait_time = between(1, 3)
    weight = 3

    @task(5)
    def home(self):
        self.client.get("/", name="GET /")

    @task(2)
    def match_detail(self):
        self.client.get(f"/match/{MATCH_ID}/", name="GET /match")

    @task(2)
    def select_floor(self):
        self.client.get(f"/matches/select-floor/{MATCH_ID}/", name="GET /select-floor")

    @task(3)
    def select_block(self):
        self.client.get(f"/matches/select-block/{MATCH_ID}/", name="GET /select-block")


class BlockPagePressure(HttpUser):
    wait_time = between(0.5, 1.5)
    weight = 1

    @task
    def select_block_heavy(self):
        self.client.get(f"/matches/select-block/{MATCH_ID}/", name="GET select-block heavy")
