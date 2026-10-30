import requests


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080", timeout: int = 60):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, method: str, path: str, **kw):
        try:
            r = requests.request(method, self.base + path, timeout=self.timeout, **kw)
        except requests.ConnectionError:
            raise ApiError(f"Не удаётся подключиться к API ({self.base}). Запущен ли сервер: uvicorn api.main:app ?")
        except requests.Timeout:
            raise ApiError("Сервер слишком долго отвечает (таймаут).")

        if r.status_code >= 400:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text

            if isinstance(detail, list):
                detail = "; ".join(str(d.get("msg", d)) for d in detail)

            raise ApiError(f"Ошибка {r.status_code}: {detail}")

        return r.json()


    def health(self):
        return self._request("GET", "/health")


    def genres(self):
        return self._request("GET", "/genres")

    def search(self, q, limit=30):
        return self._request("GET", "/movies/search", params={"q": q, "limit": limit})

    def movie(self, movie_id):
        return self._request("GET", f"/movies/{movie_id}")

    def popular(self, limit=10, genre=None, min_year=None):
        p = {"limit": limit}
        if genre: p["genre"] = genre
        if min_year: p["min_year"] = min_year
        return self._request("GET", "/movies/popular", params=p)

    def item_based(self, movie_id, method="cosine", limit=10):
        return self._request("GET", f"/recommendations/item-based/{movie_id}",
                             params={"method": method, "limit": limit})

    def content(self, movie_id, limit=10):
        return self._request("GET", f"/recommendations/content/{movie_id}", params={"limit": limit})

    def user_based(self, user_id, limit=10):
        return self._request("GET", f"/recommendations/user-based/{user_id}", params={"limit": limit})

    def personal(self, user_id, alpha=0.6, limit=10):
        return self._request("GET", f"/recommendations/personal/{user_id}", params={"alpha": alpha, "limit": limit})

    def explain_user(self, user_id, movie_id, limit=10):
        return self._request("GET", f"/explain/user-based/{user_id}/{movie_id}", params={"limit": limit})

    def explain_item(self, movie_id, rec_id, method="cosine"):
        return self._request("GET", f"/explain/item-based/{movie_id}/{rec_id}", params={"method": method})

    def explain_content(self, movie_id, rec_id):
        return self._request("GET", f"/explain/content/{movie_id}/{rec_id}")

    def get_user(self, user_id):
        return self._request("GET", f"/users/{user_id}")

    def create_user(self, username):
        return self._request("POST", "/users", json={"username": username})

    def user_ratings(self, user_id, limit=100):
        return self._request("GET", f"/users/{user_id}/ratings", params={"limit": limit})

    def reviews(self, movie_id, limit=30):
        return self._request("GET", f"/movies/{movie_id}/reviews", params={"limit": limit})

    def rate(self, user_id, movie_id, rating, comment=None):
        return self._request("POST", "/ratings",
                             json={"user_id": user_id, "movie_id": movie_id, "rating": rating, "comment": comment})