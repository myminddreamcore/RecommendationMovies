
from datetime import date

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, ForeignKey, Index, Integer, Numeric, SmallInteger,
                        String, Text, UniqueConstraint, text)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    favorite_genre: Mapped[str | None] = mapped_column(String(60))
    created_at: Mapped[date | None] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    ratings: Mapped[list["Rating"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Movie(Base):
    __tablename__ = "movies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    title_ru: Mapped[str] = mapped_column(Text, nullable=False)
    title_orig: Mapped[str | None] = mapped_column(Text)
    title_translated: Mapped[bool | None] = mapped_column(Boolean)
    year: Mapped[int | None] = mapped_column(SmallInteger)
    genres_ru: Mapped[str | None] = mapped_column(Text)
    tags_ru: Mapped[str | None] = mapped_column(Text)
    country_ru: Mapped[str | None] = mapped_column(Text)
    language_ru: Mapped[str | None] = mapped_column(Text)
    director_ru: Mapped[str | None] = mapped_column(Text)
    rating_source: Mapped[float | None] = mapped_column(Numeric(4, 2))
    n_raters_source: Mapped[int | None] = mapped_column(Integer)
    douban_id: Mapped[int | None] = mapped_column(BigInteger)
    imdb: Mapped[str | None] = mapped_column(Text)
    ratings: Mapped[list["Rating"]] = relationship(back_populates="movie")


class Rating(Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "movie_id", name="uq_rating_user_movie"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_rating_range"),
        Index("ix_ratings_movie", "movie_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    movie_id: Mapped[int] = mapped_column(ForeignKey("movies.id", ondelete="CASCADE"), nullable=False)
    rating: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)
    review_date: Mapped[date | None] = mapped_column(Date, server_default=text("CURRENT_DATE"))
    useful_num: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    source: Mapped[str] = mapped_column(String(10), server_default=text("'import'"))
    user: Mapped["User"] = relationship(back_populates="ratings")
    movie: Mapped["Movie"] = relationship(back_populates="ratings")
