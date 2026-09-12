"""
DealerCenter inventory import.

Ported from the DealerPilot importer in `hbayatne/rank-pilot`, which was written
against real DealerCenter "Active Inventory" exports and is tested against their
actual quirks: year/make/model packed into one `VehicleInfo` string, leading
spaces in headers, multi-word makes, body-style suffixes on the model, and
pricing spread across four possible columns.

Two changes from the original, both deliberate:

* **Money is cents.** A DMS export gives dollars as text; converting once, here,
  means no rule downstream ever does float arithmetic on someone's gross.
* **Cost is first-class.** `VehicleCost` and the flooring columns are what turn
  this from an inventory list into a financial picture — they are the difference
  between "you have 14 aged units" and "you have $214,000 of cash sitting on the
  lot past 90 days". Nothing here invents a number: when a column is absent the
  field stays None and every downstream finding says so.
"""
import csv
import io
import re
import xml.etree.ElementTree as ET

# Known makes, longest-first so multi-word makes match before their first token.
_MAKES = [
    "ALFA ROMEO", "ASTON MARTIN", "LAND ROVER", "MERCEDES-BENZ", "ROLLS-ROYCE",
    "MINI", "RAM", "GMC", "BMW", "KIA", "ACURA", "AUDI", "BUICK", "CADILLAC",
    "CHEVROLET", "CHRYSLER", "DODGE", "FIAT", "FORD", "GENESIS", "HONDA", "HYUNDAI",
    "INFINITI", "JAGUAR", "JEEP", "LEXUS", "LINCOLN", "MASERATI", "MAZDA",
    "MITSUBISHI", "NISSAN", "PORSCHE", "SUBARU", "TESLA", "TOYOTA", "VOLKSWAGEN",
    "VOLVO", "SCION", "SATURN", "PONTIAC", "HUMMER", "SUZUKI", "BENTLEY",
    "FERRARI", "LAMBORGHINI", "MCLAREN", "SMART", "ISUZU", "MERCURY",
]
_MAKES_SORTED = sorted(_MAKES, key=len, reverse=True)

_BODY = re.compile(
    r"\s+(SPORT UTILITY|SUPER CAB|CREW CAB|EXTENDED CAB|QUAD CAB|KING CAB|"
    r"REGULAR CAB|SEDAN|COUPE|CONVERTIBLE|HATCHBACK|WAGON|PICKUP|MINIVAN|VAN|"
    r"CARGO|SUV|TRUCK)(\s+\dD)?\s*\d?D?\s*$", re.IGNORECASE)

_STATUS = {
    "IN INVENTORY": "frontline",
    "IN RECON": "recon",
    "INBOUND": "recon",
    "SOLD": "sold",
}

_PHOTO_COLS = ("Photos", "PhotoURLs", "PhotoUrls", "Pictures", "PictureURLs",
               "Images", "ImageURLs", "ImageUrls", "VehicleImageURLs", "ImageURL",
               "PhotoURL")
_PHOTO_SPLIT = re.compile(r"[|;,\s]+")

_DETAIL_COLS = {
    "ext_color": ("Color", "ExteriorColor", "Exterior Color"),
    "int_color": ("InteriorColor", "Interior Color", "InteriorColour"),
    "body_style": ("BodyStyle", "Body Style", "Body"),
    "engine": ("Engine", "EngineDescription"),
    "transmission": ("Transmission", "Trans"),
    "drivetrain": ("DriveTrain", "Drivetrain", "Drive"),
    "fuel": ("FuelType", "Fuel", "Fuel Type"),
    "certified": ("Certified", "CPO"),
    "description": ("Description", "Comments", "SellerComments", "VehicleComments"),
}

# Columns we read for money. Listed explicitly so the feed inspector can tell an
# operator exactly which of their cost columns we found — and which we didn't.
_COST_COLS = ("VehicleCost", "Cost", "UnitCost", "TotalCost", "ACV")
_RECON_COST_COLS = ("ReconCost", "ReconditioningCost", "RepairCost", "TotalReconCost")
_PRICE_COLS = ("SpecialPrice", "AdvertisingPrice", "AskingPrice", "VehiclePrice",
               "InternetPrice", "ListPrice", "RetailPrice")
_FLOORING_COLS = ("ActualFlooringCost", "EstimatedFlooringCost", "FlooringCost")


def _title(s):
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), s) if s else s


def parse_vehicle_info(s):
    """'2018 PORSCHE MACAN SPORT UTILITY 4D' → (2018, 'Porsche', 'Macan', 'Sport Utility 4D')."""
    s = (s or "").strip()
    year = None
    m = re.match(r"((?:19|20)\d{2})\b\s*", s)
    if m:
        year = int(m.group(1))
        s = s[m.end():]
    up = s.upper()
    make = None
    for mk in _MAKES_SORTED:
        if up.startswith(mk + " ") or up == mk:
            make = mk
            s = s[len(mk):].strip()
            break
    if not make:
        parts = s.split()
        make = parts[0] if parts else ""
        s = " ".join(parts[1:])
    trim = ""
    bm = _BODY.search(s)
    if bm:
        trim = s[bm.start():].strip()
        s = s[:bm.start()].strip()
    return year, _title(make) or None, _title(s.strip()) or None, _title(trim) or None


def _date(v):
    """'06/30/2026 00:00:00' or '2026-06-30' → ISO date."""
    s = (v or "").strip().split()[0] if v else ""
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        mo, da, yr = m.groups()
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    m = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        yr, mo, da = m.groups()
        return f"{yr}-{int(mo):02d}-{int(da):02d}"
    return None


def _num(v):
    if v is None:
        return None
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?", str(v))
    if not m:
        return None
    return float(m.group(0).replace(",", ""))


def _cents(v):
    """Dollars as exported → integer cents, or None when the column is absent.

    None and 0 mean different things here and must not be conflated: a missing
    cost means we cannot compute margin and the finding has to say so, while a
    zero cost is a real (and alarming) data point.
    """
    n = _num(v)
    return None if n is None else int(round(n * 100))


def _first_cents(row, cols):
    for col in cols:
        if col in row:
            c = _cents(row.get(col))
            if c is not None:
                return c, col
    return None, None


def _price_cents(row):
    """Advertised price: Special, then Advertising, then Asking, then Vehicle."""
    for col in _PRICE_COLS:
        c = _cents(row.get(col))
        if c and c > 0:
            return c
    return None


def _photo_count(row):
    for col in _PHOTO_COLS:
        raw = (row.get(col) or "").strip()
        if raw:
            return len([u for u in _PHOTO_SPLIT.split(raw) if u.lower().startswith("http")])
    return 0


def _details(row):
    out = {}
    for key, cols in _DETAIL_COLS.items():
        for col in cols:
            val = (row.get(col) or "").strip()
            if val:
                out[key] = val
                break
    return out


def map_row(row):
    """One header-keyed CSV row → a vehicle dict, or None when unusable."""
    vin = (row.get("Vin") or row.get("VIN") or "").strip().upper()
    info = row.get("VehicleInfo") or ""
    stock = (row.get("StockNumber") or row.get("Stock") or "").strip()
    if not vin and not info.strip() and not stock:
        return None
    year, make, model, trim = parse_vehicle_info(info)
    if year is None:
        year = int(_num(row.get("Year")) or 0) or None
    make = make or (row.get("Make") or "").strip() or None
    model = model or (row.get("Model") or "").strip() or None

    cost_cents, cost_col = _first_cents(row, _COST_COLS)
    recon_cents, _ = _first_cents(row, _RECON_COST_COLS)
    flooring_cents, _ = _first_cents(row, _FLOORING_COLS)
    mileage = _num(row.get("Mileage") or row.get("Odometer"))

    details = _details(row)
    if recon_cents is not None:
        details["recon_cost_cents"] = recon_cents
    if cost_col:
        details["cost_column"] = cost_col

    return {
        "source": "dealercenter",
        "vin": vin or None,
        "stock_no": stock or None,
        "year": year, "make": make, "model": model, "trim": trim,
        "mileage": int(mileage) if mileage is not None else None,
        "price_cents": _price_cents(row),
        # Total cost carried: acquisition plus recon. That total is what is
        # actually tied up in the unit, and it is what a dealer means by "cost".
        "cost_cents": (None if cost_cents is None
                       else cost_cents + (recon_cents or 0)),
        "flooring_cents": flooring_cents,
        "status": _STATUS.get((row.get("InventoryStatus") or "").strip().upper(), "frontline"),
        "date_in_stock": _date(row.get("DateInStock") or row.get("StockDate")),
        "photo_count": _photo_count(row),
        "details": details,
    }


def _sniff(text):
    head = text[:4000]
    counts = {d: head.count(d) for d in (",", "\t", "|", ";")}
    return max(counts, key=counts.get) if any(counts.values()) else ","


def parse_csv(text):
    """Parse a DealerCenter CSV/TSV export. Delimiter is auto-detected and
    headers are stripped, because real exports arrive with leading spaces."""
    if not text or not text.strip():
        return []
    delim = _sniff(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    rows = list(reader)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    out = []
    for raw in rows[1:]:
        if not any((c or "").strip() for c in raw):
            continue
        row = {header[i]: (raw[i].strip() if i < len(raw) else "")
               for i in range(len(header))}
        v = map_row(row)
        if v:
            out.append(v)
    return out


def _xtext(el, *names):
    want = {n.lower() for n in names}
    for child in el:
        if child.tag.split("}")[-1].lower() in want:
            return (child.text or "").strip() or None
    return None


def parse_xml(text):
    """Best-effort extraction from an XML inventory feed — any element carrying
    a VIN child. Some DealerCenter exports and syndication feeds are XML."""
    try:
        root = ET.fromstring(text)
    except Exception:
        return []
    out, seen = [], set()
    for el in root.iter():
        vin = (_xtext(el, "vin", "vehicleidentificationnumber") or "").upper()
        if not vin or len(vin) < 11 or vin in seen:
            continue
        seen.add(vin)
        cost = _cents(_xtext(el, "cost", "vehiclecost", "unitcost"))
        out.append({
            "source": "dealercenter", "vin": vin,
            "stock_no": _xtext(el, "stocknumber", "stock"),
            "year": int(_num(_xtext(el, "year")) or 0) or None,
            "make": _xtext(el, "make"), "model": _xtext(el, "model"),
            "trim": _xtext(el, "trim"),
            "mileage": int(_num(_xtext(el, "mileage", "odometer", "miles")) or 0) or None,
            "price_cents": _cents(_xtext(el, "price", "sellingprice", "askingprice")),
            "cost_cents": cost,
            "flooring_cents": None,
            "status": "frontline",
            "date_in_stock": _date(_xtext(el, "dateinstock", "stockdate")),
            "photo_count": len([c for c in el
                                if c.tag.split("}")[-1].lower() in
                                ("image", "photo", "imageurl", "photourl")]),
            "details": {},
        })
    return out


def parse(text):
    """Parse whichever format the export arrived in."""
    return parse_xml(text) if (text or "").lstrip().startswith("<") else parse_csv(text)


def describe(text, sample=3):
    """What is in this file, before importing anything.

    An operator handing us their export should see which of their columns we
    understood — especially the cost ones — rather than discovering after the
    fact that the money column was named something we didn't look for.
    """
    t = (text or "").lstrip()
    if not t:
        return {"ok": False, "error": "That file was empty."}
    is_xml = t.startswith("<")
    vehicles = parse(text)
    columns = []
    if not is_xml:
        delim = _sniff(text)
        first = (text.splitlines() or [""])[0]
        columns = [h.strip() for h in next(csv.reader(io.StringIO(first), delimiter=delim), [])]

    known = {}
    for col in columns:
        low = col.lower()
        if low in ("vin",):
            known[col] = "VIN"
        elif col in _COST_COLS:
            known[col] = "cost"
        elif col in _RECON_COST_COLS:
            known[col] = "recon cost"
        elif col in _PRICE_COLS:
            known[col] = "price"
        elif col in _FLOORING_COLS:
            known[col] = "flooring cost"
        elif col in _PHOTO_COLS:
            known[col] = "photos"
        elif low in ("vehicleinfo", "year", "make", "model", "mileage", "odometer",
                     "inventorystatus", "dateinstock", "stockdate", "stocknumber", "stock"):
            known[col] = low
        else:
            for key, cols in _DETAIL_COLS.items():
                if col in cols:
                    known[col] = f"details · {key}"
                    break

    priced = [v for v in vehicles if v.get("price_cents")]
    costed = [v for v in vehicles if v.get("cost_cents") is not None]
    dated = [v for v in vehicles if v.get("date_in_stock")]
    return {
        "ok": True,
        "format": "xml" if is_xml else "csv",
        "vehicles": len(vehicles),
        "columns": columns,
        "understood": known,
        "ignored": [c for c in columns if c not in known],
        "coverage": {
            "with_cost": len(costed),
            "with_price": len(priced),
            "with_date_in_stock": len(dated),
            "with_vin": len([v for v in vehicles if v.get("vin")]),
        },
        # Said plainly, because these two gaps are the difference between a
        # financial picture and a list of cars.
        "warnings": [w for w in [
            ("No cost column found — we cannot show margin or capital tied up. "
             f"Looked for: {', '.join(_COST_COLS)}." if not costed else None),
            ("No date-in-stock column found — we cannot age the inventory. "
             "Looked for: DateInStock, StockDate." if not dated else None),
        ] if w],
        "sample": vehicles[:sample],
    }
