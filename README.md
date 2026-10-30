# Рекомендательная система фильмов (FastAPI + Tkinter + PostgreSQL)

## Быстрый старт (PyCharm или терминал, из корня проекта)
1. Python 3.10+; создайте виртуальное окружение и выполните `pip install -r requirements.txt`.
2. Установите PostgreSQL и создайте базу: `CREATE DATABASE movies_db ENCODING 'UTF8';`
3. Перепишите `.env` и впишите свой `DATABASE_URL` (пользователь, пароль, порт).
4. Окно 1: `uvicorn api.main:app --reload` (документация: http://127.0.0.1:8000/docs).
5. Окно 2: `python -m app.main` (справка: вкладка «Справка»).

## Состав
- `Movie_Recommender_Report.ipynb` — отчёт (данные, методы, оценка).
- `data/` — русскоязычные датасеты `movies_ru.csv`, `ratings_ru.csv`, `users_ru.csv`.
- `api/` — FastAPI, SQLAlchemy-модели, `recommender.py` (все методы рекомендаций).
- `app/` — графическое приложение (Tkinter), клиент API, справка.
- `sql/schema.sql` — схема БД.

## Известные ограничения
Перевод датасетов выполнен неполный, данные на 2018 год, из Китая. 
