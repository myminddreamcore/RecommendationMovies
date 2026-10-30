
from typing import List, Optional

from pydantic import BaseModel, Field


class MovieItem(BaseModel):
    movie_id: int
    title_ru: str
    year: Optional[int] = None
    genres_ru: Optional[str] = None
    country_ru: Optional[str] = None
    avg_rating: Optional[float] = Field(None, description="Средняя оценка пользователей (1–5)")
    n_ratings: Optional[int] = Field(None, description="Количество оценок")
    score: Optional[float] = Field(None, description="Значение метода: взвешенный рейтинг / сходство / прогноз оценки")
    cf_score: Optional[float] = Field(None, description="(персональные) вклад коллаборативной части, 0–1")
    content_score: Optional[float] = Field(None, description="(персональные) вклад сходства по содержанию, 0–1")
    reason: Optional[str] = None


class MovieDetail(MovieItem):
    title_orig: Optional[str] = None
    tags_ru: Optional[str] = None
    language_ru: Optional[str] = None
    director_ru: Optional[str] = None


class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=100, description="Имя пользователя")


class UserOut(BaseModel):
    id: int
    username: str
    favorite_genre: Optional[str] = None
    n_ratings: int = 0


class RatingCreate(BaseModel):
    user_id: int
    movie_id: int
    rating: int = Field(..., ge=1, le=5, description="Оценка от 1 до 5")
    comment: Optional[str] = Field(None, max_length=2000, description="Текст отзыва (необязательно)")


class RatingOut(BaseModel):
    user_id: int
    movie_id: int
    title_ru: Optional[str] = None
    username: Optional[str] = None
    rating: int
    comment: Optional[str] = None
    review_date: Optional[str] = None


class RatingSaved(BaseModel):
    status: str
    created: bool
    rating: RatingOut


class HelpCommand(BaseModel):
    name: str
    method: str
    path: str
    description: str
    params: List[str]


class NeighborMovie(BaseModel):
    movie_id: int
    title_ru: str
    rating: float = Field(..., description="Оценка этого пользователя")
    your_rating: Optional[float] = Field(None, description="Ваша оценка этого же фильма (если вы его оценивали)")


class NeighborOut(BaseModel):
    user_id: int
    username: str
    similarity: float = Field(..., description="Сходство вкусов с вами (косинус, 0–1)")
    rating: float = Field(..., description="Оценка рекомендуемого фильма этим пользователем")
    common_movies: int = Field(..., description="Сколько фильмов оценили и вы, и он")
    n_rated: int = Field(..., description="Сколько всего фильмов он оценил")
    movies: List[NeighborMovie]


class ExplainUserBased(BaseModel):
    movie_id: int
    title_ru: str
    n_neighbors: int = Field(..., description="Сколько похожих пользователей использовано")
    n_raters: int = Field(..., description="Сколько из них оценили этот фильм")
    predicted_rating: Optional[float] = Field(None, description="Взвешенная средняя оценка похожих пользователей")
    neighbors: List[NeighborOut]


class CoRater(BaseModel):
    user_id: int
    username: str
    base_rating: float
    rec_rating: float


class ExplainItemBased(BaseModel):
    base_title: str
    rec_title: str
    similarity: Optional[float] = None
    n_common: int
    n_both_liked: int
    users: List[CoRater]


class ExplainContent(BaseModel):
    base_title: str
    rec_title: str
    shared: List[str]
    only_rec: List[str]
