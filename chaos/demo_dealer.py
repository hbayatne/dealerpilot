"""
A dealership demo — a DealerCenter export and the mailbox that goes with it.

Clearly labelled sample data, never presented as real findings. It exists to show
the thing no single system can show: the DMS knows a unit has sat for months and
what it cost; the mailbox knows somebody asked about that exact car and nobody
answered. Put side by side, that is a number a dealer can act on before lunch.

The lot is deliberately ordinary — a few aged units, one priced under water, a
couple with no photos, and one unit with no cost at all so the "our figures are a
floor, not a total" path is exercised rather than assumed.
"""
import datetime

DEMO_BANNER = "DEMO DATA — this is a sample dealership, not your real findings."

ORG = {"name": "Car Place Dallas (demo)", "website": "https://example.com",
       "industry": "Automotive", "domains": ["carplacedallas.example"]}

US = "carplacedallas.example"
REP = f"fernando@{US}"
DESK = f"sales@{US}"


def _d(base, days):
    return (base - datetime.timedelta(days=days)).strftime("%m/%d/%Y")


def inventory_csv(now=None):
    """A DealerCenter 'Active Inventory' export, in the real column layout."""
    now = (now or datetime.datetime.utcnow()).date()
    header = ("VehicleInfo, Vin, InventoryStatus, VehicleSaleType, StockNumber, Color, "
              "Mileage, VehiclePrice, AskingPrice, AdvertisingPrice, SpecialPrice, "
              "VehicleCost, ReconCost, DateInStock, ActualFlooringCost, PhotoURLs")
    photo = "https://img.example/1.jpg|https://img.example/2.jpg"
    rows = [
        # Aged, expensive, and someone emailed about it — the headline finding.
        f"2018 PORSCHE MACAN SPORT UTILITY 4D, WP1AA2A55JLB04974, IN INVENTORY, BOTH, "
        f"JLB04974, WHITE, 87002, 38990, 38990, 0, 0, 31200, 1450, {_d(now, 141)}, 410, {photo}",
        # Aged and quietly bleeding flooring.
        f"2016 LAND ROVER RANGE ROVER SPORT UTILITY 4D, SALGS2EF2GA270670, IN INVENTORY, "
        f"BOTH, GA270670, GRAY, 87860, 27500, 27500, 0, 0, 24900, 2100, {_d(now, 118)}, 520, {photo}",
        # Under water — advertised below what it cost.
        f"2013 MERCEDES-BENZ CLS-CLASS CLS 550 COUPE 4D, WDDLJ7DB1DA058400, IN INVENTORY, "
        f"RETAIL, DA058400, GOLD, 72600, 12990, 12990, 0, 11990, 12400, 900, "
        f"{_d(now, 64)}, 180, {photo}",
        # Frontline but unshoppable: no price.
        f"2020 FORD F-150 XLT SUPER CAB, 1FTEW1EP0LFA00001, IN INVENTORY, BOTH, "
        f"LFA00001, BLUE, 41200, 0, 0, 0, 0, 28400, 600, {_d(now, 22)}, 0, {photo}",
        # Frontline but unshoppable: no photos.
        f"2019 TOYOTA CAMRY SE SEDAN 4D, 4T1B11HK5KU000002, IN INVENTORY, BOTH, "
        f"KU000002, SILVER, 55300, 21490, 21490, 0, 0, 17800, 350, {_d(now, 31)}, 0, ",
        # Stuck in recon for weeks.
        f"2017 HONDA ACCORD EX SEDAN 4D, 1HGCR2F800A000003, IN RECON, BOTH, "
        f"0A000003, BLACK, 96400, 15990, 15990, 0, 0, 12100, 2400, {_d(now, 38)}, 0, {photo}",
        # No cost in the export at all — the honest-gap path.
        f"2021 CHEVROLET EQUINOX LT SPORT UTILITY 4D, 2GNAXKEV4M0000004, IN INVENTORY, "
        f"BOTH, M0000004, RED, 38900, 23990, 23990, 0, 0, , , {_d(now, 19)}, 0, {photo}",
        # A healthy unit, so the lot isn't uniformly on fire.
        f"2022 NISSAN ROGUE SV SPORT UTILITY 4D, 5N1BT3BB9NC000005, IN INVENTORY, BOTH, "
        f"NC000005, WHITE, 27400, 26990, 26990, 0, 0, 21500, 400, {_d(now, 11)}, 0, {photo}",
    ]
    return header + "\n" + "\n".join(rows)


def _msg(mid, subject, frm, name, to, date, body, refs=None, headers=None):
    h = {"message-id": mid}
    if refs:
        h["references"] = refs
        h["in-reply-to"] = refs
    h.update(headers or {})
    return {"source_id": mid, "message_id": mid, "headers": h, "subject": subject,
            "from_name": name, "from_addr": frm,
            "to": [{"name": "", "addr": a} for a in (to if isinstance(to, list) else [to])],
            "cc": [], "date": date, "body": body, "attachments": []}


def _dt(now, days=0, hours=0):
    return (now + datetime.timedelta(days=days, hours=hours)).strftime(
        "%a, %d %b %Y %H:%M:%S -0500")


def mailbox(now=None):
    """The store's mailbox over the same period."""
    now = now or datetime.datetime.utcnow().replace(microsecond=0)
    m = []

    # The headline: a live buyer for a 141-day-old unit, ignored for a week.
    m += [
        _msg("<c1a>", "2018 Macan - still available?", "marcus.webb@gmail.com",
             "Marcus Webb", REP, _dt(now, -9),
             "Hi, I saw the white 2018 Porsche Macan on your site (stock JLB04974). "
             "Is it still available, and would you take 36 for it? I can come in "
             "this week with cash."),
        _msg("<c1b>", "Re: 2018 Macan - still available?", "marcus.webb@gmail.com",
             "Marcus Webb", REP, _dt(now, -6),
             "Following up — is anyone there? Still interested in the Macan.",
             refs="<c1a>"),
    ]

    # A second enquiry on another aged unit, also unanswered.
    m.append(
        _msg("<c2a>", "Range Rover question", "dana.osei@gmail.com", "Dana Osei", DESK,
             _dt(now, -5),
             "What's the out the door price on the 2016 Land Rover Range Rover you "
             "have listed? Any service records?"))

    # A promise made and not kept, on a unit that has since sold-adjacent aged.
    m += [
        _msg("<c3a>", "Trade value on my Accord", "priya.raman@gmail.com", "Priya Raman",
             REP, _dt(now, -14),
             "Can you give me a trade number on my 2015 Accord if I buy the Camry?"),
        _msg("<c3b>", "Re: Trade value on my Accord", REP, "Fernando Reyes",
             "priya.raman@gmail.com", _dt(now, -13),
             "Hi Priya — I'll run the numbers and call you Thursday with a trade "
             "figure.", refs="<c3a>"),
    ]

    # Healthy thread that must stay silent — answered and closed.
    m += [
        _msg("<c4a>", "Rogue availability", "sam.fields@gmail.com", "Sam Fields", DESK,
             _dt(now, -4), "Is the 2022 Nissan Rogue still there?"),
        _msg("<c4b>", "Re: Rogue availability", DESK, "Car Place Dallas",
             "sam.fields@gmail.com", _dt(now, -4, 2),
             "It is! Priced at $26,990. Happy to hold it for a viewing.", refs="<c4a>"),
        _msg("<c4c>", "Re: Rogue availability", "sam.fields@gmail.com", "Sam Fields",
             DESK, _dt(now, -4, 3), "Perfect, thanks!", refs="<c4a>"),
    ]

    # Noise that must stay silent.
    m.append(
        _msg("<c5>", "Your weekly AutoTrader performance report",
             "no-reply@autotradermail.example", "AutoTrader", DESK, _dt(now, -2),
             "Your listings received 412 views this week.",
             headers={"list-unsubscribe": "<https://x/u>", "precedence": "bulk"}))
    m.append(
        _msg("<c6>", "Lot cleanup Saturday", REP, "Fernando Reyes", DESK, _dt(now, -1),
             "Can we get the back row detailed before the weekend? I'll be in at 8."))

    return m


def build(now=None):
    """(inventory_csv, messages, now) for the demo dealership."""
    now = now or datetime.datetime.utcnow().replace(microsecond=0)
    return inventory_csv(now), mailbox(now), now
