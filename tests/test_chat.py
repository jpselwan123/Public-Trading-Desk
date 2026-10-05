"""Ask: the chat. What the model is told, what it is not, what is kept, and the page's side of it.
No network: the model is a stand-in that keeps what it is asked."""
from support import *  # noqa: F401,F403
import world  # noqa: E402

NOW = datetime(2026, 10, 5, 15, 0, tzinfo=timezone.utc)


class Model:
    """A stand-in for OpenAI's responses endpoint: it answers in turn and keeps every request body."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers) or ["It is up on the day."], []

    def __call__(self, req, timeout=None):
        self.requests.append(json.loads(req.data))
        i = min(len(self.requests) - 1, len(self.answers) - 1)
        return FakeResponse({"output_text": self.answers[i]})

    def told(self, n=-1):
        return self.requests[n]["input"][-1]["content"][0]["text"]


def desk():
    """The parts of the built desk the chat reads, with the amounts made easy to search for."""
    card = {"ticker": "KSTR", "name": "Keystone Beverage Co.", "revenue": 4.2e9, "revenue_basis": "quarters", "revenue_asof": "2026-06-30",
            "price": {"close": 57.42, "as_of": "2026-10-05", "year": 0.06, "year_vs_market": -0.02},
            "next_earnings": {"date": "2026-10-21"}, "rating": {"label": "Hold"}}
    other = {"ticker": "NVLX", "name": "Novalux Inc.", "price": {"close": 90.0, "as_of": "2026-10-05"}, "rating": {"why_not": "too little history"},
             "next_earnings": {"date": "2026-09-01"}}
    rows = [{"ticker": "KSTR", "weight": 0.31, "pl_pct": 0.05, "days_held": 400, "value": 123456.78, "cost": 111111.11, "pl": 12345.67,
             "rating": {"label": "Hold"}},
            {"ticker": "NVLX", "weight": 0.69, "pl_pct": -0.1, "days_held": 30, "value": 987654.32, "cost": 1097393.69, "pl": -109739.37,
             "rating": {"label": None, "why_not": "x"}}]
    news = {"level": "95%", "companies": {"KSTR": {"days": [
        {"session": "2026-10-02", "move": 0.012, "unusual": False, "items": [{"headline": "Keystone raises its dividend", "sources": ["Reuters"]}] * 6, "filings": []},
        {"session": "2026-09-01", "move": 0.0, "unusual": False, "items": [{"headline": "An old story", "sources": ["FT"]}], "filings": []}]}}}
    return {"today": "2026-10-05", "companies": [card, other], "positions": {"rows": rows},
            "account": {"total": 2222222.22, "cash": 22222.22}, "company_news": news,
            "digest": {"important": [{"ticker": "KSTR", "headline": "Annual report", "label": "Annual report", "date": "2026-10-01"}],
                       "insider_buys": [], "ratings": [{"ticker": "NVLX", "label": "Hold", "was": None}],
                       "moves": [{"ticker": "NVLX", "change": -0.11, "from": "2026-09-28", "to": "2026-10-05"}]}}


class WhatTheModelIsToldTests(unittest.TestCase):
    def test_a_ticker_is_picked_out_of_a_question_only_when_the_desk_knows_it(self):
        data = desk()
        self.assertEqual(chat.mentioned("How is KSTR doing against SPY?", data), ["KSTR", "SPY"])
        self.assertEqual(chat.mentioned("what about $nvlx and $kstr", data), ["NVLX", "KSTR"])
        self.assertEqual(chat.mentioned("is it a good day", data), [])                           # words are not tickers
        self.assertEqual(chat.mentioned("TSLA or AAPL?", data), [])                              # nothing held on them
        self.assertEqual(chat.mentioned("KSTR KSTR", data), ["KSTR"])
        self.assertEqual(chat.mentioned(None, data), [])

    def test_a_company_the_desk_covers_is_given_its_figures_its_rating_and_this_weeks_news(self):
        got = chat.facts(desk(), ["KSTR"])
        facts = got["KSTR"]
        self.assertEqual(facts["company"], "Keystone Beverage Co.")
        self.assertIn("Hold (made by the dashboard from published measures, not advice)", facts["the_dashboards_own_rating"])
        days = facts["this_weeks_news"]
        self.assertEqual([d["day"] for d in days], ["2 October 2026"])                           # the week's, not September's
        self.assertEqual(len(days[0]["headlines"]), 4)                                           # four at most a day
        self.assertEqual(chat.facts(desk(), ["NVLX"])["NVLX"]["the_dashboards_own_rating"], "not rated: too little history")
        self.assertIn("holds no figures", chat.facts(desk(), ["TSLA"])["TSLA"])
        self.assertEqual(list(chat.facts(desk(), ["A", "B", "C", "D", "E"]))[:4], ["A", "B", "C"])        # three at most
        self.assertNotIn("the_owners_holdings", chat.facts(desk(), ["KSTR"]))

    def test_the_owners_holdings_go_only_when_asked_and_then_as_shares_and_percentages_never_amounts(self):
        data = desk()
        mine = chat.facts(data, ["KSTR"], mine=True)["the_owners_holdings"]
        text = json.dumps(mine)
        self.assertIn("KSTR: 31.0% of the holdings; +5.0% on cost; held 400 days; the dashboard's rating: Hold", text)
        self.assertIn("NVLX: 69.0% of the holdings; -10.0% on cost", text)
        self.assertEqual(mine["cash_share_of_the_account"], "1.0%")
        for amount in ("123456", "987654", "111111", "1097393", "12345", "109739", "2222222", "22222"):
            self.assertNotIn(amount, text)                                                          # not a value, a cost, a gain, the total or the cash
        self.assertIn("rating change: NVLX unrated to Hold", text)
        self.assertIn("important filing: KSTR Annual report (1 October 2026)", text)
        self.assertIn("results on 21 October 2026", text)
        self.assertNotIn("1 September 2026", text)                                                # results already past are not "coming up"

    def test_the_chart_on_show_is_told_as_the_page_shows_it(self):
        chart = charts.demo_chart(world.demo_prices(date(2026, 10, 5)), "KO", "1M")
        got = chat.facts(desk(), ["KSTR"], chart=chart)
        self.assertEqual(got["the_chart_on_show"]["range"], "1M")


class AnswerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()
        charts._cache.clear()

    def ask(self, model, message="How is KSTR doing?", **kw):
        return chat.ask(self.folder, desk(), message, key="k", model="m", opener=model, now=kw.pop("now", NOW), **kw)

    def test_a_question_goes_with_the_rules_the_facts_and_the_conversation_so_far(self):
        model = Model("Its shares are up 6% over the year.", "Next results are on 21 October 2026.")
        first = self.ask(model, ticker="KSTR")
        body = model.requests[0]
        self.assertEqual(body["model"], "m")
        self.assertEqual(body["instructions"], chat.SYSTEM)
        self.assertEqual(body["max_output_tokens"], chat.MAX_OUTPUT_TOKENS)
        self.assertEqual(len(body["input"]), 1)
        told = model.told(0)
        self.assertIn('"company": "Keystone Beverage Co."', told)
        self.assertTrue(told.rstrip().endswith("Question: How is KSTR doing?"))
        self.assertEqual([t["role"] for t in first["turns"]], ["user", "assistant"])
        self.assertEqual(first["turns"][1]["text"], "Its shares are up 6% over the year.")
        second = self.ask(model, "And when are results?")
        roles = [m["role"] for m in model.requests[1]["input"]]
        self.assertEqual(roles, ["user", "assistant", "user"])                                    # the first exchange comes along
        self.assertEqual(model.requests[1]["input"][1]["content"][0]["type"], "output_text")
        self.assertEqual(model.requests[1]["input"][0]["content"][0]["type"], "input_text")
        self.assertEqual(len(second["turns"]), 4)
        self.assertEqual(chat.turns(self.folder)[0]["text"], "How is KSTR doing?")

    def test_the_holdings_are_sent_only_with_the_tick(self):
        model = Model()
        self.ask(model)
        self.assertNotIn("the_owners_holdings", model.told())
        self.ask(model, "What should I look at today?", mine=True)
        self.assertIn("the_owners_holdings", model.told())
        self.assertNotIn("987654", model.told())
        self.ask(model, "What does P/E mean?")
        self.assertEqual(model.told().strip(), "Question: What does P/E mean?")                    # nothing to give: just the question

    def test_what_the_owner_is_looking_at_is_in_play_and_so_is_a_name_in_the_question(self):
        model = Model()
        self.ask(model, "Compare it with NVLX", ticker="KSTR")
        told = json.loads(model.told().split("Facts the dashboard holds:\n", 1)[1].split("\n\nQuestion:")[0])
        self.assertEqual(list(told), ["KSTR", "NVLX"])

    def test_advice_is_asked_for_again_once_and_then_refused(self):
        for phrase in ("You should buy it now.", "I recommend holding.", "It looks undervalued.", "Its price target is $70.",
                       "That is a good buy.", "I would sell it.", "Don't sell yet.", "Worth buying on the dip."):
            self.assertTrue(chat.advice_in(phrase), phrase)
        for phrase in ("The dashboard's own rating is Buy, made from published measures.", "The desk rates it Sell.",
                       "Its shares are up 6%.", "Hold on: the report is not in yet.", "Check the Filings page next.",
                       "Volume is 5,294,633 shares.", "It sells beverages."):
            self.assertFalse(chat.advice_in(phrase), phrase)
        model = Model("You should buy it.", "Its shares are up 6%. Check the News fold.")
        got = self.ask(model)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(got["turns"][-1]["text"], "Its shares are up 6%. Check the News fold.")
        self.assertEqual(model.told(), chat.RETRY)                                                  # told what was wrong
        self.assertEqual([m["role"] for m in model.requests[1]["input"]], ["user", "assistant", "user"])
        stubborn = Model("You should buy it.")
        got = self.ask(stubborn, "again?")
        self.assertEqual(len(stubborn.requests), 2)
        self.assertEqual(got["turns"][-1]["text"], chat.REFUSAL)
        self.assertFalse(chat.advice_in(chat.REFUSAL))

    def test_a_question_is_held_to_its_limits_and_a_day_has_a_count(self):
        model = Model()
        for bad, words in (("", "Type a question"), ("   ", "Type a question"), ("x" * (chat.MAX_QUESTION + 1), "under 600")):
            with self.assertRaises(chat.ChatError) as e:
                self.ask(model, bad)
            self.assertIn(words, str(e.exception))
        self.assertEqual(model.requests, [])
        small = chat.PER_DAY
        chat.PER_DAY = 3
        try:
            for i in range(3):
                got = self.ask(model, f"q{i}")
            self.assertEqual(got["left_today"], 0)
            with self.assertRaises(chat.ChatError) as e:
                self.ask(model, "one more")
            self.assertIn("today's limit of 3", str(e.exception))
            self.assertEqual(len(model.requests), 3)
            self.ask(model, "tomorrow", now=NOW + timedelta(days=1))                                # a new day
            chat.clear(self.folder)
            self.assertEqual(chat.turns(self.folder), [])
            with self.assertRaises(chat.ChatError):
                self.ask(model, "cleared, but not the count", now=NOW + timedelta(hours=1))        # clearing the talk does not clear the count
        finally:
            chat.PER_DAY = small

    def test_a_failed_request_is_said_in_words_and_keeps_nothing(self):
        def refuse(req, timeout=None):
            raise urllib.error.HTTPError(req.full_url, 429, "x", {}, None)
        with self.assertRaises(chat.ChatError) as e:
            self.ask(refuse)
        self.assertIn("rate limit", str(e.exception))
        self.assertEqual(chat.turns(self.folder), [])
        saved = os.environ.pop("OPENAI_API_KEY", None)
        real = summarise.load_env
        try:
            summarise.load_env = lambda path: None
            with self.assertRaises(chat.ChatError) as e:
                chat.ask(self.folder, desk(), "hi", opener=Model(), now=NOW)
            self.assertIn("OPENAI_API_KEY", str(e.exception))
        finally:
            summarise.load_env = real
            if saved is not None:
                os.environ["OPENAI_API_KEY"] = saved

    def test_a_conversation_that_cannot_be_read_is_never_written_over(self):
        path = os.path.join(self.folder, chat.CHAT_FILE)
        with open(path, "w") as f:
            f.write("{ not json")
        with self.assertRaises(chat.ChatError) as e:
            self.ask(Model())
        self.assertIn("nothing was written over it", str(e.exception))
        with open(path) as f:
            self.assertEqual(f.read(), "{ not json")
        with open(path, "w") as f:
            json.dump({"turns": [{"role": "robot", "text": 5}, "x", {"role": "user", "text": "kept"}], "asked": [3, "2026-10-05T01:00:00+00:00"]}, f)
        self.assertEqual([t["text"] for t in chat.turns(self.folder)], ["kept"])                    # junk is dropped, not fatal

    def test_only_the_last_turns_are_kept_and_sent(self):
        model = Model()
        for i in range(chat.MAX_TURNS // 2 + 5):
            self.ask(model, f"question {i}")
        self.assertEqual(len(chat.turns(self.folder)), chat.MAX_TURNS)
        self.assertEqual(len(model.requests[-1]["input"]), chat.HISTORY_SENT + 1)


class ChatBoundaryTests(unittest.TestCase):
    def test_the_chat_places_nothing_and_reaches_no_broker(self):
        for name in ("chat.py", "charts.py"):
            source = read(os.path.join(ROOT, name))
            self.assertNotIn(".post(", source, name)
            for forbidden in ("import t212", "import execute", "from t212", "from execute", "orders.json", "WRITE_GUARD"):
                self.assertNotIn(forbidden, source, name)
        self.assertNotIn("subprocess", read(os.path.join(ROOT, "chat.py")))

    def test_every_word_of_the_model_goes_through_the_one_function_that_holds_the_key(self):
        source = read(os.path.join(ROOT, "chat.py"))
        self.assertEqual(source.count("summarise.ask("), 2)                                         # the answer and the second try
        self.assertNotIn("urllib", source)
        self.assertNotIn("OPENAI_API_KEY", source)

    def test_the_rules_say_what_the_summaries_rules_say(self):
        for rule in ("never say buy, sell, hold, avoid", "no target price", "Never say that a news story", "never use outside knowledge",
                     "exactly as written", "under 110 words", "does not have it"):
            self.assertIn(rule.lower().replace("never say buy", "never say buy"), chat.SYSTEM.lower().replace("\\\n", ""), rule) \
                if rule != "no target price" else self.assertIn("name no target price", chat.SYSTEM)

    def test_summarise_ask_carries_a_conversation_and_changes_nothing_else(self):
        model = Model("fine")
        text, used = summarise.ask("rules", "now", key="k", model="m", opener=model, history=[("user", "a"), ("assistant", "b"), ("tool", "x"), ("user", "")])
        self.assertEqual((text, used), ("fine", "m"))
        body = model.requests[0]
        self.assertEqual([m["role"] for m in body["input"]], ["user", "assistant", "user"])       # a stranger role and an empty turn are left out
        self.assertEqual(body["input"][1]["content"], [{"type": "output_text", "text": "b"}])
        model = Model("fine")
        summarise.ask("rules", "now", key="k", model="m", opener=model)
        self.assertEqual(len(model.requests[0]["input"]), 1)


class ServerChatTests(unittest.TestCase):
    def handler(self, demo=False):
        h = server.Handler.__new__(server.Handler)
        h.folder, h.demo = tempfile.mkdtemp(), demo
        write_json(os.path.join(h.folder, "desk_data.json"), desk())
        return h

    def test_history_ask_and_clear(self):
        h = self.handler()
        self.assertEqual(h.chat_turn({"op": "history"})[1], {"ok": True, "turns": [], "left_today": chat.PER_DAY})
        real = summarise.ask
        calls = []
        summarise.ask = lambda *a, **k: (calls.append((a, k)) or ("It is up 6% over the year.", "m"))
        try:
            code, out = h.chat_turn({"message": "How is KSTR?", "ticker": "kstr", "range": "6m", "mine": True})
        finally:
            summarise.ask = real
        self.assertTrue(out["ok"])
        self.assertEqual(out["turns"][-1]["text"], "It is up 6% over the year.")
        self.assertIn("the_owners_holdings", calls[0][0][1])                                       # only `True` itself ticks it
        summarise.ask = lambda *a, **k: (calls.append((a, k)) or ("Ok.", "m"))
        try:
            h.chat_turn({"message": "again", "mine": "yes"})
        finally:
            summarise.ask = real
        self.assertNotIn("the_owners_holdings", calls[1][0][1])
        self.assertEqual(h.chat_turn({"op": "clear"})[1]["turns"], [])
        self.assertFalse(h.chat_turn({"message": ""})[1]["ok"])

    def test_the_route_is_there_and_orders_stay_with_the_mac(self):
        source = inspect.getsource(server.Handler.do_POST)
        self.assertIn('path == "/chat"', source)
        self.assertIn('path == "/chart"', source)
        if hasattr(server.Handler, "execute_order"):                                                  # the private desk: the tailnet still places none
            self.assertIn('if path == "/execute" and self._where() != "here"', source)


class ChatPageTests(unittest.TestCase):
    def head(self):
        code = read(os.path.join(ROOT, "page", "chat.js"))
        return "const esc = s => String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');\n" + \
            code[code.index("function chatHtml("):code.index("function chatDraw(")]

    def test_an_answer_is_text_paragraphs_and_lists_never_markup(self):
        out = run_javascript(self.head() + "\nconsole.log(chatHtml('<img src=x onerror=1>\\nSecond line\\n- one <b>\\n* two\\n\\nLast'));")
        self.assertEqual(out, "<p>&lt;img src=x onerror=1&gt;</p><p>Second line</p><ul><li>one &lt;b&gt;</li><li>two</li></ul><p>Last</p>")

    def test_the_panel_is_a_closed_aside_with_its_parts_and_the_page_sends_only_to_the_chat(self):
        template, code = read(os.path.join(ROOT, "desk_template.html")), read(os.path.join(ROOT, "page", "chat.js"))
        self.assertRegex(template, r'<aside class="chat" id="chat" hidden')
        for ident in ("chatLog", "chatSugg", "chatForm", "chatMine", "chatInput", "chatSend", "chatClear", "chatClose", "askBtn"):
            self.assertIn(f'id="{ident}"', template)
        self.assertEqual(re.findall(r"fetch\('([^']+)'", code), ["/chat"])
        self.assertNotRegex(code, r"#[0-9a-fA-F]{3,8}\b|rgba?\(")
        self.assertIn("never amounts", template)                                                    # the tick says what it sends
        self.assertIn("DATA.as_of", template_function("renderAsk", page_source()))                 # a past day has no chat
        self.assertIn("openChat()", read(os.path.join(ROOT, "page", "palette.js")))
        self.assertEqual(re.findall(r"localStorage\.setItem\('([^']+)'", code), ["deskChatMine"])       # only the tick is remembered here

    def test_the_questions_it_offers_follow_what_is_on_show(self):
        code = read(os.path.join(ROOT, "page", "chat.js"))
        program = code[code.index("function chatSuggestions("):code.index("// the answer as text")]
        got = json.loads(run_javascript("let chatCtx = null;\n" + program + "\nconst out = {};\n"
                         "out.none = chatSuggestions().map(s => s.q + (s.mine ? '*' : ''));\n"
                         "chatCtx = {ticker: 'KO', what: 'chart'}; out.chart = chatSuggestions().map(s => s.q);\n"
                         "chatCtx = {ticker: 'KO', what: 'company'}; out.company = chatSuggestions().map(s => s.q);\n"
                         "console.log(JSON.stringify(out));"))
        self.assertEqual(got["none"], ["What should I look at today?*", "What does P/E mean?"])      # the first asks for the holdings
        self.assertEqual(got["chart"][0], "Explain this chart")
        self.assertEqual(got["company"][0], "How is it doing against the market?")
        self.assertEqual(got["chart"][1:], got["company"][1:])


if __name__ == "__main__":
    unittest.main()
