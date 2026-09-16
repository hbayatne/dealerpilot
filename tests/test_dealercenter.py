"""DealerCenter import and the money findings it unlocks.

The cost column is the point. Most of these tests exist to prove that a missing
or zero cost behaves differently from a present one — a dashboard that silently
treats "not exported" as zero understates a dealer's capital and is worse than
showing nothing.
"""
import datetime
import os
import tempfile
import unittest

os.environ.setdefault("CHAOS_DB", os.path.join(tempfile.mkdtemp(), "dc.db"))
# The API test below drives the app through a client: cookies must survive plain
# http, and importing the app must never start background work in a test run.
os.environ.setdefault("CHAOS_SECURE_COOKIES", "0")
os.environ.setdefault("CHAOS_DISABLE_SCHEDULER", "1")

from chaos import db, demo_dealer, pipeline                       # noqa: E402
from chaos.detect import crosssystem, inventory                   # noqa: E402
from chaos.ingest import dealercenter as dc                       # noqa: E402

HEADER = ("VehicleInfo, Vin, InventoryStatus, StockNumber, Mileage, AskingPrice, "
          "SpecialPrice, VehicleCost, ReconCost, DateInStock, ActualFlooringCost, PhotoURLs")


def row(info, vin, status, stock, miles, ask, special, cost, recon, date, floor, photos=""):
    return (f"{info}, {vin}, {status}, {stock}, {miles}, {ask}, {special}, {cost}, "
            f"{recon}, {date}, {floor}, {photos}")


class Parsing(unittest.TestCase):
    def test_vehicle_info_is_split(self):
        y, mk, md, tr = dc.parse_vehicle_info("2018 PORSCHE MACAN SPORT UTILITY 4D")
        self.assertEqual((y, mk, md), (2018, "Porsche", "Macan"))
        self.assertEqual(tr, "Sport Utility 4D")

    def test_multi_word_makes(self):
        self.assertEqual(dc.parse_vehicle_info("2016 LAND ROVER RANGE ROVER SEDAN 4D")[1],
                         "Land Rover")
        self.assertEqual(dc.parse_vehicle_info("2013 MERCEDES-BENZ CLS-CLASS COUPE 4D")[1],
                         "Mercedes-Benz")

    def test_money_is_cents_and_recon_is_added_to_cost(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "WP1AA2A55JLB04974", "IN INVENTORY",
                                  "JLB04974", 87002, 19990, 0, 15993, 900,
                                  "03/02/2026", 250)
        v = dc.parse(csv)[0]
        self.assertEqual(v["price_cents"], 1999000)
        self.assertEqual(v["cost_cents"], 1689300, "cost must be acquisition + recon")
        self.assertEqual(v["flooring_cents"], 25000)

    def test_special_price_wins_over_asking(self):
        csv = HEADER + "\n" + row("2013 MERCEDES-BENZ CLS-CLASS", "WDDLJ7DB1DA058400",
                                  "IN INVENTORY", "DA058400", 72600, 17990, 15990,
                                  10142, 0, "05/15/2026", 0)
        self.assertEqual(dc.parse(csv)[0]["price_cents"], 1599000)

    def test_missing_cost_is_none_not_zero(self):
        """'Not exported' and 'costs nothing' are different facts."""
        csv = HEADER + "\n" + row("2021 CHEVROLET EQUINOX", "2GNAXKEV4M0000004",
                                  "IN INVENTORY", "M0", 38900, 23990, 0, "", "",
                                  "08/01/2026", 0)
        self.assertIsNone(dc.parse(csv)[0]["cost_cents"])

    def test_status_and_date_mapping(self):
        csv = HEADER + "\n" + row("2017 HONDA ACCORD", "1HGCR2F800A000003", "IN RECON",
                                  "0A000003", 96400, 15990, 0, 12100, 0,
                                  "06/30/2026 00:00:00", 0)
        v = dc.parse(csv)[0]
        self.assertEqual(v["status"], "recon")
        self.assertEqual(v["date_in_stock"], "2026-06-30")

    def test_blank_rows_are_skipped(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "V1", "IN INVENTORY", "S1",
                                  1, 2, 0, 3, 0, "01/01/2026", 0) + "\n, , , , , , , , , , , "
        self.assertEqual(len(dc.parse(csv)), 1)

    def test_delimiter_is_detected(self):
        tsv = HEADER.replace(", ", "\t") + "\n" + row(
            "2018 PORSCHE MACAN", "V2", "IN INVENTORY", "S2", 1, 20000, 0, 15000, 0,
            "01/01/2026", 0).replace(", ", "\t")
        self.assertEqual(len(dc.parse(tsv)), 1)


class Describe(unittest.TestCase):
    def test_names_the_cost_columns_it_found(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "V3", "IN INVENTORY", "S3",
                                  1, 20000, 0, 15000, 500, "01/01/2026", 100)
        d = dc.describe(csv)
        self.assertEqual(d["coverage"]["with_cost"], 1)
        self.assertEqual(d["warnings"], [])
        self.assertIn("VehicleCost", d["understood"])

    def test_warns_loudly_when_there_is_no_cost_column(self):
        hdr = "VehicleInfo, Vin, InventoryStatus, AskingPrice, DateInStock"
        csv = hdr + "\n2018 PORSCHE MACAN, V4, IN INVENTORY, 20000, 01/01/2026"
        d = dc.describe(csv)
        self.assertEqual(d["coverage"]["with_cost"], 0)
        self.assertTrue(any("cost" in w.lower() for w in d["warnings"]))


class CostBasis(unittest.TestCase):
    """Whether recon is added on top of cost, or already inside it.

    Getting this backwards does not produce a slightly wrong number — it moves
    every margin in the product. Overstating cost invents negative-margin
    findings, which is the expensive kind of wrong, so a column that names
    itself a total is believed and anything else is treated as acquisition.
    """

    TOTAL_HEADER = HEADER.replace("VehicleCost", "TotalCost")

    def test_acquisition_column_gets_recon_added(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "CB1", "IN INVENTORY", "S1",
                                  1, 20000, 0, 15000, 900, "01/01/2026", 0)
        v = dc.parse(csv)[0]
        self.assertEqual(v["cost_cents"], 1590000)
        self.assertTrue(v["details"]["recon_added"])

    def test_a_total_column_is_believed_as_a_total(self):
        csv = self.TOTAL_HEADER + "\n" + row("2018 PORSCHE MACAN", "CB2", "IN INVENTORY",
                                             "S2", 1, 20000, 0, 15000, 900, "01/01/2026", 0)
        v = dc.parse(csv)[0]
        self.assertEqual(v["cost_cents"], 1500000, "recon must not be double-counted")
        self.assertFalse(v["details"]["recon_added"])

    def test_the_operator_can_overrule_either_way(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "CB3", "IN INVENTORY", "S3",
                                  1, 20000, 0, 15000, 900, "01/01/2026", 0)
        self.assertEqual(dc.parse(csv, add_recon=False)[0]["cost_cents"], 1500000)
        total = self.TOTAL_HEADER + "\n" + row("2018 PORSCHE MACAN", "CB4", "IN INVENTORY",
                                               "S4", 1, 20000, 0, 15000, 900, "01/01/2026", 0)
        self.assertEqual(dc.parse(total, add_recon=True)[0]["cost_cents"], 1590000)

    def test_describe_states_the_arithmetic_before_importing(self):
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "CB5", "IN INVENTORY", "S5",
                                  1, 20000, 0, 15000, 900, "01/01/2026", 0)
        cb = dc.describe(csv)["cost_basis"]
        self.assertEqual((cb["cost_column"], cb["recon_column"]), ("VehicleCost", "ReconCost"))
        self.assertTrue(cb["recon_added"])
        self.assertIn("VehicleCost + ReconCost", cb["sentence"])
        flipped = dc.describe(csv, add_recon=False)["cost_basis"]
        self.assertFalse(flipped["recon_added"])
        self.assertIn("already includes", flipped["sentence"])

    def test_no_recon_column_is_said_plainly(self):
        hdr = "VehicleInfo, Vin, InventoryStatus, AskingPrice, VehicleCost, DateInStock"
        csv = hdr + "\n2018 PORSCHE MACAN, CB6, IN INVENTORY, 20000, 15000, 01/01/2026"
        cb = dc.describe(csv)["cost_basis"]
        self.assertIsNone(cb["recon_column"])
        self.assertFalse(cb["recon_added"])
        self.assertIn("No recon column", cb["sentence"])

    def test_the_choice_is_remembered_across_uploads(self):
        """A second export costed on a different basis would move every margin
        in the product with no explanation. The first answer is kept."""
        from fastapi.testclient import TestClient
        from chaos import ratelimit
        from chaos.app import app
        ratelimit.reset()
        c = TestClient(app)
        c.post("/api/signup", json={"email": "recon@x.test", "password": "password1234",
                                    "name": "R"})
        oid = c.post("/api/orgs", json={"name": "Recon Motors",
                                        "industry": "Automotive"}).json()["org"]["id"]
        csv = HEADER + "\n" + row("2018 PORSCHE MACAN", "CB7", "IN INVENTORY", "S7",
                                  1, 20000, 0, 15000, 900, "01/01/2026", 0)
        r = c.post(f"/api/orgs/{oid}/inventory/import",
                   json={"content": csv, "filename": "a.csv", "add_recon": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(r.json()["cost_basis"]["recon_added"])
        # A later upload that says nothing must not silently switch basis.
        p = c.post(f"/api/orgs/{oid}/inventory/preview",
                   json={"content": csv, "filename": "b.csv"}).json()["preview"]
        self.assertFalse(p["cost_basis"]["recon_added"])
        self.assertEqual(c.get(f"/api/orgs/{oid}/inventory").json()["vehicles"][0]["cost_cents"],
                         1500000)


class Storage(unittest.TestCase):
    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "store.db")
        import importlib
        importlib.reload(db)
        db.init()
        self.uid = db.create_user("dc@x.test", "x")
        self.oid = db.create_org("Lot", user_id=self.uid)

    def test_reimport_updates_rather_than_duplicating(self):
        v = {"vin": "WP1AA2A55JLB04974", "price_cents": 1999000, "cost_cents": 1500000,
             "status": "frontline"}
        db.upsert_vehicle(self.oid, v)
        db.upsert_vehicle(self.oid, dict(v, price_cents=1899000))
        self.assertEqual(db.vehicle_count(self.oid), 1)
        self.assertEqual(db.vehicles(self.oid)[0]["price_cents"], 1899000)

    def test_vin_is_case_insensitive(self):
        db.upsert_vehicle(self.oid, {"vin": "ABC123DEF456GHI78", "status": "frontline"})
        db.upsert_vehicle(self.oid, {"vin": "abc123def456ghi78", "status": "frontline"})
        self.assertEqual(db.vehicle_count(self.oid), 1)

    def test_inventory_is_tenant_scoped(self):
        other = db.create_org("Other lot", user_id=self.uid)
        db.upsert_vehicle(self.oid, {"vin": "V00000000000000A1", "status": "frontline"})
        self.assertEqual(db.vehicle_count(other), 0)


class MoneyFindings(unittest.TestCase):
    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "money.db")
        import importlib
        importlib.reload(db)
        db.init()
        self.uid = db.create_user("m@x.test", "x")
        self.oid = db.create_org("Lot", user_id=self.uid,
                                 domains=demo_dealer.ORG["domains"])
        self.org = db.get_org(self.oid)
        self.today = datetime.date(2026, 9, 12)
        self.now = "2026-09-12T10:00:00"

    def _add(self, **kw):
        base = {"status": "frontline", "photo_count": 2}
        base.update(kw)
        return db.upsert_vehicle(self.oid, base)[0]

    def _detectors(self):
        return {f["detector"] for f, _ in
                inventory.run(self.org, now_iso=self.now, today=self.today)}

    def test_aged_capital_counts_only_exported_cost(self):
        self._add(vin="A1", cost_cents=3120000, date_in_stock="2026-04-01")
        self._add(vin="A2", cost_cents=2490000, date_in_stock="2026-05-01")
        self._add(vin="A3", cost_cents=None, date_in_stock="2026-04-15")   # no cost
        aged, evidence = next(
            (f, ev) for f, ev in inventory.run(self.org, now_iso=self.now, today=self.today)
            if f["detector"] == "aged_capital")
        self.assertEqual(aged["impact_cents"], 3120000 + 2490000,
                         "a unit with no exported cost must not be counted as zero")
        detail = " ".join(e["detail"] or "" for e in evidence).lower()
        self.assertIn("floor", detail,
                      "the finding must say the total is understated, not imply it is complete")

    def test_negative_margin_is_the_real_loss(self):
        self._add(vin="N1", price_cents=1199000, cost_cents=1330000,
                  date_in_stock="2026-07-10")
        f = next(f for f, _ in inventory.run(self.org, now_iso=self.now, today=self.today)
                 if f["detector"] == "negative_margin")
        self.assertEqual(f["impact_cents"], 1330000 - 1199000)

    def test_no_margin_finding_without_a_cost(self):
        self._add(vin="N2", price_cents=1199000, cost_cents=None,
                  date_in_stock="2026-07-10")
        self.assertNotIn("negative_margin", self._detectors())

    def test_unsellable_units_are_aggregated(self):
        self._add(vin="U1", price_cents=None, cost_cents=2840000,
                  date_in_stock="2026-09-01")
        self._add(vin="U2", price_cents=2149000, cost_cents=1780000,
                  photo_count=0, date_in_stock="2026-09-01")
        f = next(f for f, _ in inventory.run(self.org, now_iso=self.now, today=self.today)
                 if f["detector"] == "unsellable_units")
        self.assertIn("2", f["title"])

    def test_missing_cost_is_reported_rather_than_hidden(self):
        for i in range(4):
            self._add(vin=f"MC{i}", price_cents=2000000, cost_cents=None,
                      date_in_stock="2026-09-01")
        self.assertIn("missing_cost_data", self._detectors())

    def test_a_healthy_lot_produces_nothing(self):
        self._add(vin="H1", price_cents=2699000, cost_cents=2150000,
                  date_in_stock="2026-09-01")
        self.assertEqual(self._detectors(), set())


class CrossSystem(unittest.TestCase):
    """The reason this integration exists: the mailbox and the lot together."""

    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "cross.db")
        import importlib
        importlib.reload(db)
        db.init()
        self.uid = db.create_user("x@x.test", "x")
        self.oid = db.create_org(demo_dealer.ORG["name"], user_id=self.uid,
                                 domains=demo_dealer.ORG["domains"])
        self.org = db.get_org(self.oid)
        self.now_dt = datetime.datetime(2026, 9, 9, 10, 0)     # a Wednesday
        self.now = self.now_dt.isoformat(timespec="seconds")
        self.today = self.now_dt.date()

    def _load(self):
        csv_text, msgs, _ = demo_dealer.build(self.now_dt)
        for v in dc.parse(csv_text):
            db.upsert_vehicle(self.oid, v)
        pipeline.ingest(self.org, msgs)

    def test_unanswered_buyer_on_a_unit_we_still_own(self):
        self._load()
        found = [f for f, _ in crosssystem.run(self.org, now_iso=self.now, today=self.today)]
        lead = [f for f in found if f["detector"] == "unanswered_lead_on_unit"]
        self.assertTrue(lead, "a matched buyer on an unsold unit must be found")
        macan = next((f for f in lead if "Macan" in f["title"]), None)
        self.assertIsNotNone(macan, "the stock number in the message should match the unit")
        self.assertEqual(macan["impact_cents"], 3899000,
                         "value is the advertised price of the unit, from the DMS")
        self.assertEqual(sorted(macan["source_systems"]), ["dealercenter", "email"])

    def test_evidence_cites_both_systems(self):
        self._load()
        for f, ev in crosssystem.run(self.org, now_iso=self.now, today=self.today):
            if f["detector"] != "unanswered_lead_on_unit":
                continue
            kinds = {e.get("ref_kind") for e in ev}
            self.assertIn("message", kinds)
            self.assertIn("vehicle", kinds)

    def test_an_answered_thread_produces_nothing(self):
        """Sam Fields asked about the Rogue, got an answer, said thanks."""
        self._load()
        titles = " ".join(f["title"] for f, _ in
                          crosssystem.run(self.org, now_iso=self.now, today=self.today))
        self.assertNotIn("Rogue", titles)

    def test_no_inventory_means_no_cross_system_findings(self):
        _csv, msgs, _ = demo_dealer.build(self.now_dt)
        pipeline.ingest(self.org, msgs)
        self.assertEqual(crosssystem.run(self.org, now_iso=self.now, today=self.today), [])

    def test_a_sold_unit_is_never_matched(self):
        csv_text, msgs, _ = demo_dealer.build(self.now_dt)
        for v in dc.parse(csv_text):
            v["status"] = "sold"
            db.upsert_vehicle(self.oid, v)
        pipeline.ingest(self.org, msgs)
        self.assertEqual(crosssystem.run(self.org, now_iso=self.now, today=self.today), [])


class VehicleMatching(unittest.TestCase):
    def setUp(self):
        self.vehicles = [{
            "id": 1, "vin": "WP1AA2A55JLB04974", "stock_no": "JLB04974",
            "year": 2018, "make": "Porsche", "model": "Macan", "status": "frontline"}]
        self.by_vin = {"WP1AA2A55JLB04974": self.vehicles[0]}
        self.by_stock = {"JLB04974": self.vehicles[0]}

    def _m(self, text, subject=""):
        return crosssystem.match_vehicle(text, subject, self.by_vin, self.by_stock,
                                         self.vehicles)

    def test_vin_match(self):
        hit = self._m("Interested in WP1AA2A55JLB04974, is it available?")
        self.assertIsNotNone(hit)
        self.assertTrue(hit[1].startswith("VIN"))

    def test_stock_number_match(self):
        self.assertIsNotNone(self._m("About stock JLB04974 please"))

    def test_year_make_model_match(self):
        self.assertIsNotNone(self._m("Is the 2018 Porsche Macan still there?"))

    def test_make_alone_is_not_enough(self):
        """'Do you have any Porsches?' must not attach a name to one specific car."""
        self.assertIsNone(self._m("Do you sell Porsche?"))

    def test_wrong_year_does_not_match(self):
        self.assertIsNone(self._m("Looking for a 2021 Porsche Macan"))

    def test_unrelated_text_does_not_match(self):
        self.assertIsNone(self._m("Can I get a copy of my invoice?"))


if __name__ == "__main__":
    unittest.main()


class ScoreHonesty(unittest.TestCase):
    """An overall score built from one dimension is a claim about the whole
    business that we cannot support from a fraction of it."""

    def setUp(self):
        os.environ["CHAOS_DB"] = os.path.join(tempfile.mkdtemp(), "prov.db")
        import importlib
        importlib.reload(db)
        db.init()
        self.uid = db.create_user("s@x.test", "x")
        self.oid = db.create_org("Lot", user_id=self.uid,
                                 domains=demo_dealer.ORG["domains"])
        db.upsert_integration(self.oid, "dealercenter", label="x",
                              config={"sample_data": True})

    def test_inventory_alone_is_provisional(self):
        from chaos import score
        csv_text, _m, _n = demo_dealer.build(datetime.datetime(2026, 9, 9, 10, 0))
        for v in dc.parse(csv_text):
            db.upsert_vehicle(self.oid, v)
        r = score.compute(self.oid)
        self.assertTrue(r["provisional"])
        self.assertTrue(r["coverage"]["provisional"])
        self.assertNotIn("chaos", r["band_label"].lower(),
                         "a provisional reading must not be labelled as a chaos band")

    def test_needs_owner_matches_the_list_shown(self):
        """The headline count and the list under it must never disagree."""
        from chaos import attention
        for i in range(4):
            db.upsert_finding(self.oid, f"k{i}", category="revenue", title=f"F{i}",
                              detector="d", severity="medium", confidence=0.7)
        ranked = attention.rank(self.oid)
        self.assertEqual(attention.summarize(self.oid, ranked)["needs_owner"],
                         len(attention.today(self.oid, ranked)))
