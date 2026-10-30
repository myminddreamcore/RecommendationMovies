import argparse
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from .api_client import ApiClient, ApiError
from .help_text import HELP_TEXT

RESULT_COLUMNS = [("n", "№", 40), ("title", "Название", 300), ("year", "Год", 55), ("genres", "Жанры", 190),
                  ("country", "Страна", 100), ("avg", "Ср. оценка", 80), ("cnt", "Оценок", 70),
                  ("score", "Значение", 80)]


class ExplainPanel(ttk.LabelFrame):

    def __init__(self, parent, title, left_cols, right_cols=None, link=False):
        super().__init__(parent, text=title, padding=4)
        self.link, self.details = link, []
        self.summary = ttk.Label(self, text="Выберите строку в списке рекомендаций выше.", wraplength=1000,
                                 justify="left")
        self.summary.pack(fill="x", anchor="w", pady=(0, 4))
        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        lf, self.left = self._tree(body, left_cols)
        body.add(lf, weight=2)

        self.right = None
        if right_cols:
            rf, self.right = self._tree(body, right_cols)
            body.add(rf, weight=3)

        if link:
            self.left.bind("<<TreeviewSelect>>", lambda e: self._show_details())

    @staticmethod
    def _tree(parent, cols):
        frame = ttk.Frame(parent)
        # show="headings" скрывает первый пустой столбец treeview
        tree = ttk.Treeview(frame, columns=[c[0] for c in cols], show="headings", height=7, selectmode="browse")
        for cid, text, width in cols:
            tree.heading(cid, text=text)
            tree.column(cid, width=width, anchor="w" if cid in ("title", "feature") else "center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, tree

    def clear(self, text="Выберите строку в списке рекомендаций выше."):

        self.summary.configure(text=text)
        self.details = []
        for t in (self.left, self.right):
            if t is not None:
                t.delete(*t.get_children())

    def set_left(self, rows, details=None):
        # заполнение левой таблицы и сохранение данных для правой
        self.left.delete(*self.left.get_children())
        for i, v in enumerate(rows):
            self.left.insert("", "end", iid=str(i), values=v)
        self.details = details or []
        # если есть связь, сразу выбираем первую строку, чтобы показать детали
        if self.link and rows:
            self.left.selection_set("0")

    def set_right(self, rows):
        # заполнение правой таблицы
        self.right.delete(*self.right.get_children())
        for i, v in enumerate(rows):
            self.right.insert("", "end", iid=str(i), values=v)

    def _show_details(self):
        # при клике на строку слева берем соответствующие данные из self.details и показываем справа
        sel = self.left.selection()
        if sel and self.right is not None and int(sel[0]) < len(self.details):
            self.set_right(self.details[int(sel[0])])


class App(tk.Tk):
    def __init__(self, api_url: str, user_id: int | None = None):
        super().__init__()
        self.title("Рекомендации фильмов")
        self.geometry("1400x880")
        self.minsize(1100, 700)
        self.api = ApiClient(api_url)
        self.user = None
        self.selected = None
        self.q = queue.Queue()

        self._build_ui()

        self.after(100, self._poll)
        self.run_async(self.api.genres, self._fill_genres, quiet=True)

        if user_id:
            self.login(user_id)

    #очередь запросов
    def run_async(self, func, on_ok, *args, quiet=False, on_error=None):
        self.status.set("Выполняется запрос…")

        def work():
            try:
                self.q.put((on_ok, func(*args), None, quiet, on_error))
            except ApiError as e:
                self.q.put((on_ok, None, str(e), quiet, on_error))
            except Exception as e:
                self.q.put((on_ok, None, f"Непредвиденная ошибка: {e}", quiet, on_error))

        threading.Thread(target=work, daemon=True).start()

    #берет запрос из очереди
    def _poll(self):
        try:
            while True:
                on_ok, result, error, quiet, on_error = self.q.get_nowait()
                if error:
                    self.status.set(error)
                    if on_error:
                        on_error(error)
                    if not quiet:
                        messagebox.showerror("Ошибка", error)
                else:
                    self.status.set("Готово")
                    on_ok(result)
        except queue.Empty:
            pass

        self.after(100, self._poll)


    def _build_ui(self):
        top = ttk.Frame(self, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Пользователь №").pack(side="left")
        self.user_entry = ttk.Entry(top, width=8)
        self.user_entry.pack(side="left", padx=4)
        ttk.Button(top, text="Войти", command=self.on_login).pack(side="left")
        self.user_label = ttk.Label(top, text="Не выполнен вход", foreground="#a00")
        self.user_label.pack(side="left", padx=12)



        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=6, pady=4)




        left = ttk.Frame(body, padding=4)
        body.add(left, weight=1)
        ttk.Label(left, text="Поиск фильма", font=("", 11, "bold")).pack(anchor="w")
        row = ttk.Frame(left)
        row.pack(fill="x", pady=3)
        self.search_entry = ttk.Entry(row)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda e: self.on_search())
        ttk.Button(row, text="Найти", command=self.on_search).pack(side="left", padx=4)



        self.search_tree = self._make_tree(left,
                                           [("title", "Название", 230), ("year", "Год", 50), ("cnt", "Оценок", 60)],
                                           height=18)
        self.search_tree.bind("<<TreeviewSelect>>", lambda e: self._select_from(self.search_tree, self._search_items))



        self.selected_label = ttk.Label(left, text="Фильм не выбран", wraplength=330, justify="left", foreground="#036")
        self.selected_label.pack(anchor="w", pady=6)



        right = ttk.Frame(body, padding=4)
        body.add(right, weight=4)
        self.tabs = ttk.Notebook(right)
        self.tabs.pack(fill="both", expand=True)


        self._tab_popular()
        self._tab_item()
        self._tab_content()
        self._tab_user()
        self._tab_rate()
        self._tab_mine()
        self._tab_help()



        self.status = tk.StringVar(value="Готово")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w", padding=3).pack(fill="x", side="bottom")

    @staticmethod
    def _make_tree(parent, columns, height=15):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", height=height, selectmode="browse")
        for cid, text, width in columns:
            tree.heading(cid, text=text)
            tree.column(cid, width=width, anchor="w" if cid in ("title", "genres", "country") else "center")
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return tree

    def _results_tab(self, title, explain_factory=None, on_select=None):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text=title)
        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(0, 6))

        if explain_factory is None:
            tree = self._make_tree(tab, RESULT_COLUMNS, height=18)
        else:
            pw = ttk.PanedWindow(tab, orient="vertical")
            pw.pack(fill="both", expand=True)
            top = ttk.Frame(pw)
            tree = self._make_tree(top, RESULT_COLUMNS, height=8)
            pw.add(top, weight=1)

            self._last_panel = explain_factory(pw)
            pw.add(self._last_panel, weight=1)

            tree.bind("<<TreeviewSelect>>", lambda e, t=tree: on_select(t))

        tree.bind("<Double-1>", lambda e, t=tree: self._select_from_result(t))
        return tab, controls, tree

    def _tab_popular(self):
        tab, c, self.pop_tree = self._results_tab("Популярные")
        ttk.Label(c, text="Жанр:").pack(side="left")
        self.pop_genre = ttk.Combobox(c, width=18, state="readonly", values=["(любой)"])
        self.pop_genre.current(0)
        self.pop_genre.pack(side="left", padx=4)
        ttk.Label(c, text="Сколько:").pack(side="left", padx=(10, 0))
        self.pop_limit = ttk.Spinbox(c, from_=1, to=50, width=5)
        self.pop_limit.set(10)
        self.pop_limit.pack(side="left", padx=4)
        ttk.Button(c, text="Показать топ", command=self.on_popular).pack(side="left", padx=10)

    def _tab_item(self):
        tab, c, self.item_tree = self._results_tab(
            "Похожие (по фильмам)",
            lambda parent: ExplainPanel(parent, "На чём основана рекомендация: кто оценил оба фильма",
                                        [("user", "Пользователь", 170), ("base", "Оценка исходного фильма", 150),
                                         ("rec", "Оценка рекомендованного", 150)]),
            self.on_explain_item)
        self.item_panel = self._last_panel
        ttk.Label(c, text="Метод:").pack(side="left")
        self.item_method = ttk.Combobox(c, width=10, state="readonly", values=["cosine", "pearson"])
        self.item_method.current(0)
        self.item_method.pack(side="left", padx=4)
        ttk.Label(c, text="Сколько:").pack(side="left", padx=(10, 0))
        self.item_limit = ttk.Spinbox(c, from_=1, to=50, width=5)
        self.item_limit.set(10)
        self.item_limit.pack(side="left", padx=4)
        ttk.Button(c, text="Найти похожие", command=self.on_item).pack(side="left", padx=10)

    def _tab_content(self):
        tab, c, self.content_tree = self._results_tab(
            "Похожие по содержанию",
            lambda parent: ExplainPanel(parent, "На чём основана рекомендация: совпавшие признаки",
                                        [("feature", "Совпадает у обоих фильмов", 330)],
                                        [("feature", "Есть только у рекомендованного", 330)]),
            self.on_explain_content)
        self.content_panel = self._last_panel
        ttk.Label(c, text="Сколько:").pack(side="left")
        self.content_limit = ttk.Spinbox(c, from_=1, to=50, width=5)
        self.content_limit.set(10)
        self.content_limit.pack(side="left", padx=4)
        ttk.Button(c, text="Найти по содержанию", command=self.on_content).pack(side="left", padx=10)

    def _tab_user(self):
        tab, c, self.user_tree = self._results_tab(
            "Для пользователя",
            lambda parent: ExplainPanel(
                parent, "На чём основана рекомендация: похожие на вас пользователи (слева) и их фильмы (справа)",
                [("user", "Похожий пользователь", 150), ("sim", "Сходство", 70), ("rating", "Оценил этот фильм", 110),
                 ("common", "Общих фильмов", 100)],
                [("title", "Фильм этого пользователя", 300), ("their", "Его оценка", 80), ("yours", "Ваша оценка", 90),
                 ("match", "Совпадение", 90)], link=True),
            self.on_explain_user)
        self.user_panel = self._last_panel
        self.user_kind = tk.StringVar(value="personal")
        ttk.Radiobutton(c, text="Персональные (гибрид)", variable=self.user_kind, value="personal").pack(side="left")
        ttk.Radiobutton(c, text="По пользователям (CF)", variable=self.user_kind, value="user").pack(side="left",
                                                                                                     padx=8)
        ttk.Label(c, text="Вес CF (alpha):").pack(side="left")
        self.alpha = ttk.Spinbox(c, from_=0, to=1, increment=0.1, width=5)
        self.alpha.set(0.6)
        self.alpha.pack(side="left", padx=4)
        ttk.Label(c, text="Сколько:").pack(side="left", padx=(10, 0))
        self.user_limit = ttk.Spinbox(c, from_=1, to=50, width=5)
        self.user_limit.set(10)
        self.user_limit.pack(side="left", padx=4)
        ttk.Button(c, text="Показать", command=self.on_user_recs).pack(side="left", padx=10)

    def _tab_rate(self):
        tab = self.rate_tab = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(tab, text="Оценить фильм")
        self.rate_title = ttk.Label(tab, text="Выберите фильм слева (поиск) или двойным щелчком в списке рекомендаций",
                                    font=("", 12, "bold"), wraplength=700, justify="left")
        self.rate_title.pack(anchor="w")
        self.rate_info = ttk.Label(tab, text="", wraplength=700, justify="left")
        self.rate_info.pack(anchor="w", pady=4)
        row = ttk.Frame(tab)
        row.pack(anchor="w", pady=6)
        ttk.Label(row, text="Ваша оценка:").pack(side="left")
        self.rate_var = tk.IntVar(value=4)
        for v in range(1, 6):
            ttk.Radiobutton(row, text=str(v), variable=self.rate_var, value=v).pack(side="left", padx=6)
        ttk.Label(tab, text="Отзыв (необязательно):").pack(anchor="w")
        self.comment = tk.Text(tab, height=5, width=80, wrap="word")
        self.comment.pack(anchor="w", pady=4)
        btns = ttk.Frame(tab)
        btns.pack(anchor="w", pady=4)
        ttk.Button(btns, text="Сохранить оценку", command=self.on_rate).pack(side="left")
        ttk.Button(btns, text="Показать отзывы на фильм", command=self.on_reviews).pack(side="left", padx=10)
        self.reviews_tree = self._make_tree(tab, [("user", "Пользователь", 150), ("rating", "Оценка", 60),
                                                  ("date", "Дата", 90), ("comment", "Отзыв", 450)], height=8)

    def _tab_mine(self):
        tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(tab, text="Мои оценки")
        ttk.Button(tab, text="Обновить", command=self.on_mine).pack(anchor="w", pady=(0, 6))
        self.mine_tree = self._make_tree(tab, [("title", "Фильм", 330), ("rating", "Оценка", 70), ("date", "Дата", 90),
                                               ("comment", "Отзыв", 450)], height=18)

    def _tab_help(self):
        self.help_tab = ttk.Frame(self.tabs, padding=8)
        self.tabs.add(self.help_tab, text="Справка")
        self.help_box = tk.Text(self.help_tab, wrap="word", font=("Consolas", 10))
        sb = ttk.Scrollbar(self.help_tab, command=self.help_box.yview)
        self.help_box.configure(yscrollcommand=sb.set)
        self.help_box.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.help_box.insert("1.0", HELP_TEXT)
        self.help_box.configure(state="disabled")


    def _fill_genres(self, genres):
        self.pop_genre.configure(values=["(любой)"] + list(genres))


    def _fill_results(self, tree, items):
        tree.delete(*tree.get_children())
        tree._items = items
        for i, m in enumerate(items, 1):
            tree.insert("", "end", iid=str(i - 1), values=(
                i, m.get("title_ru", ""), m.get("year") or "", m.get("genres_ru") or "", m.get("country_ru") or "",
                m.get("avg_rating") if m.get("avg_rating") is not None else "",
                m.get("n_ratings") if m.get("n_ratings") is not None else "",
                m.get("score") if m.get("score") is not None else ""))
        if not items:
            self.status.set("Ничего не найдено (для этого запроса нет рекомендаций)")

    def _set_selected(self, m):
        self.selected = m
        year = f" ({m['year']})" if m.get("year") else ""
        self.selected_label.configure(text=f"Выбран: {m['title_ru']}{year}\nЖанры: {m.get('genres_ru') or '—'}")
        self.rate_title.configure(text=f"{m['title_ru']}{year}")
        self.rate_info.configure(text=f"Жанры: {m.get('genres_ru') or '—'}\nСтрана: {m.get('country_ru') or '—'}\n"
                                      f"Средняя оценка: {m.get('avg_rating') or '—'}  (оценок: {m.get('n_ratings') or 0})")

    def _select_from(self, tree, items):
        sel = tree.selection()
        if sel:
            self._set_selected(items[int(sel[0])])

    @property
    def _search_items(self):
        return getattr(self.search_tree, "_items", [])

    def _select_from_result(self, tree):
        sel = tree.selection()
        if sel:
            self._set_selected(tree._items[int(sel[0])])
            self.tabs.select(self.rate_tab)

    def _need_movie(self):
        if not self.selected:
            messagebox.showinfo("Выберите фильм", "Сначала найдите фильм слева и выберите его в списке.")
            return False
        return True

    def _need_user(self):
        if not self.user:
            messagebox.showinfo("Нужен вход", "Введите номер пользователя и нажмите «Войти» (или создайте нового).")
            return False
        return True

    @staticmethod
    def _int(widget, default=10):
        try:
            return max(1, min(50, int(widget.get())))
        except ValueError:
            return default

    def _selected_row(self, tree):
        sel = tree.selection()
        items = getattr(tree, "_items", [])
        return items[int(sel[0])] if sel and int(sel[0]) < len(items) else None

    def _explain(self, tree, panel, request, render):
        m = self._selected_row(tree)
        if not m:
            return
        #токены нужны, чтобы если пользователь быстро кликнет два раза, показался результат только последнего клика, а не первого
        self._explain_token = getattr(self, "_explain_token", 0) + 1
        token = self._explain_token
        panel.clear("Загрузка…")

        def done(res):
            # проверяем, актуален ли еще этот запрос
            if token == self._explain_token:
                render(m, res)

        self.run_async(lambda: request(m), done, quiet=True,
                       on_error=lambda msg: token == self._explain_token and panel.clear(
                           f"Не удалось получить объяснение: {msg}"))

    def on_explain_user(self, tree):
        if not self.user:
            return
        uid = self.user["id"]
        self._explain(tree, self.user_panel, lambda m: self.api.explain_user(uid, m["movie_id"]), self._render_user)

    def _render_user(self, m, res):
        p = self.user_panel
        if not res["neighbors"]:
            p.clear(
                f"«{m['title_ru']}»: ни один из {res['n_neighbors']} похожих на вас пользователей этот фильм не оценил. "
                f"Рекомендация построена по содержанию: по жанрам и тегам фильмов, которые вы оценили высоко.")
            return
        p.summary.configure(text=(
            f"«{m['title_ru']}»: из {res['n_neighbors']} самых похожих на вас пользователей этот фильм оценили {res['n_raters']}; "
            f"их взвешенная средняя оценка — {res['predicted_rating']}. Ниже показаны самые похожие из них. "
            f"Выберите пользователя слева — справа его фильмы; «✓» — вы тоже оценили этот фильм."))
        left, details = [], []
        for n in res["neighbors"]:
            left.append((n["username"], n["similarity"], n["rating"], f"{n['common_movies']} из {n['n_rated']}"))
            rows = []
            for mv in n["movies"]:
                yours = mv.get("your_rating")
                if yours is None:
                    rows.append((mv["title_ru"], mv["rating"], "—", ""))
                else:
                    agree = abs(yours - mv["rating"]) <= 1 or (yours >= 4 and mv["rating"] >= 4)
                    rows.append((mv["title_ru"], mv["rating"], yours, "✓ совпадает" if agree else "✗ расходится"))
            details.append(rows)
        p.set_left(left, details)

    def on_explain_item(self, tree):
        base = getattr(self, "_item_base", None)
        if base:
            self._explain(tree, self.item_panel, lambda m: self.api.explain_item(base[0], m["movie_id"], base[1]),
                          self._render_item)

    def _render_item(self, m, res):
        p = self.item_panel
        sim = f" Сходство (косинус/корреляция): {res['similarity']}." if res.get("similarity") is not None else ""
        p.summary.configure(text=(f"«{res['base_title']}» и «{res['rec_title']}» оценили {res['n_common']} человек; "
                                  f"{res['n_both_liked']} из них поставили обоим фильмам 4–5.{sim} Ниже — примеры таких пользователей."))
        p.set_left([(u["username"], u["base_rating"], u["rec_rating"]) for u in res["users"]])

    def on_explain_content(self, tree):
        base = getattr(self, "_content_base", None)
        if base:
            self._explain(tree, self.content_panel, lambda m: self.api.explain_content(base, m["movie_id"]),
                          self._render_content)

    def _render_content(self, m, res):
        p = self.content_panel
        p.summary.configure(
            text=f"«{res['base_title']}» и «{res['rec_title']}»: совпало признаков — {len(res['shared'])}.")
        p.set_left([(f,) for f in res["shared"]] or [("(нет общих признаков)",)])
        p.set_right([(f,) for f in res["only_rec"]])

    def login(self, user_id):
        self.run_async(self.api.get_user, self._logged_in, user_id)

    def _logged_in(self, u):
        self.user = u
        self.user_entry.delete(0, "end")
        self.user_entry.insert(0, str(u["id"]))
        self.user_label.configure(text=f"Вы: {u['username']} (№{u['id']}, оценок: {u['n_ratings']})", foreground="#060")

    def on_login(self):
        try:
            self.login(int(self.user_entry.get()))
        except ValueError:
            messagebox.showwarning("Вход", "Номер пользователя должен быть целым числом.")


    def on_search(self):
        q = self.search_entry.get().strip()
        if not q:
            return
        self.run_async(self.api.search, self._search_done, q)

    def _search_done(self, items):
        self.search_tree.delete(*self.search_tree.get_children())
        self.search_tree._items = items
        for i, m in enumerate(items):
            self.search_tree.insert("", "end", iid=str(i),
                                    values=(m["title_ru"], m.get("year") or "", m.get("n_ratings") or 0))
        if not items:
            self.status.set("Ничего не найдено")

    def on_popular(self):
        genre = self.pop_genre.get()
        genre = None if genre in ("", "(любой)") else genre
        self.run_async(lambda: self.api.popular(self._int(self.pop_limit), genre),
                       lambda r: self._fill_results(self.pop_tree, r))

    def on_item(self):
        if self._need_movie():
            mid, method, lim = self.selected["movie_id"], self.item_method.get(), self._int(self.item_limit)
            self._item_base = (mid, method)
            self.item_panel.clear()
            self.run_async(lambda: self.api.item_based(mid, method, lim),
                           lambda r: self._fill_results(self.item_tree, r))

    def on_content(self):
        if self._need_movie():
            mid, lim = self.selected["movie_id"], self._int(self.content_limit)
            self._content_base = mid
            self.content_panel.clear()
            self.run_async(lambda: self.api.content(mid, lim), lambda r: self._fill_results(self.content_tree, r))

    def on_user_recs(self):
        if not self._need_user():
            return
        uid, lim, kind = self.user["id"], self._int(self.user_limit), self.user_kind.get()
        self.user_panel.clear()
        try:
            alpha = max(0.0, min(1.0, float(self.alpha.get())))
        except ValueError:
            alpha = 0.6
        func = (lambda: self.api.personal(uid, alpha, lim)) if kind == "personal" else (
            lambda: self.api.user_based(uid, lim))
        self.run_async(func, lambda r: self._fill_results(self.user_tree, r))

    def on_rate(self):
        if not (self._need_user() and self._need_movie()):
            return
        uid, mid, rating = self.user["id"], self.selected["movie_id"], self.rate_var.get()
        comment = self.comment.get("1.0", "end").strip() or None
        self.run_async(lambda: self.api.rate(uid, mid, rating, comment), self._rated)

    def _rated(self, res):
        verb = "сохранена" if res["created"] else "обновлена"
        messagebox.showinfo("Готово", f"Оценка {verb}: «{res['rating']['title_ru']}» — {res['rating']['rating']}/5")
        self.comment.delete("1.0", "end")
        self.login(self.user["id"])
        self.on_mine()

    def on_reviews(self):
        if not self._need_movie():
            return
        mid = self.selected["movie_id"]

        def show(items):
            self.reviews_tree.delete(*self.reviews_tree.get_children())
            for i, r in enumerate(items):
                self.reviews_tree.insert("", "end", iid=str(i), values=(
                r.get("username") or "", r["rating"], r.get("review_date") or "", r.get("comment") or ""))
            if not items:
                self.status.set("Отзывов с текстом пока нет")

        self.run_async(lambda: self.api.reviews(mid), show)

    def on_mine(self):
        if not self._need_user():
            return
        uid = self.user["id"]

        def show(items):
            self.mine_tree.delete(*self.mine_tree.get_children())
            for i, r in enumerate(items):
                self.mine_tree.insert("", "end", iid=str(i), values=(
                r.get("title_ru") or r["movie_id"], r["rating"], r.get("review_date") or "", r.get("comment") or ""))

        self.run_async(lambda: self.api.user_ratings(uid), show)


def main():
    ap = argparse.ArgumentParser(description="Приложение «Рекомендации фильмов»", epilog=HELP_TEXT,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api-url", default=os.getenv("API_URL", "http://127.0.0.1:8080"), help="адрес FastAPI-сервера")
    ap.add_argument("--user", type=int, default=None, help="войти под этим номером пользователя")
    args = ap.parse_args()
    App(args.api_url, args.user).mainloop()


if __name__ == "__main__":
    main()