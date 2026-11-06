"""
UK EV Charging Network Database (synthetic, 2025–2026)
Author: Student
Purpose: Generate a reproducible SQLite database for an MSc SQL assignment.

All records are synthetic. No real drivers, vehicle identifiers, payment details,
or personal contact information are used. A fixed random seed makes the build
reproducible. Deliberate data-quality defects are confined to the raw import
staging table; the curated relational tables enforce integrity constraints.
"""
import sqlite3
import random
from datetime import datetime, timedelta, date
from pathlib import Path

SEED = 20261105
random.seed(SEED)
DB_PATH = Path(__file__).with_name("uk_ev_charging_2026.sqlite")

def choose_weighted(items):
    values, weights = zip(*items)
    return random.choices(values, weights=weights, k=1)[0]

def build_database(db_path=DB_PATH):
    if db_path.exists():
        db_path.unlink()
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    cur = con.cursor()

    # Separate tables reduce repeated descriptive data and support referential integrity.
    cur.executescript("""
    CREATE TABLE regions (
        region_id INTEGER PRIMARY KEY,
        region_name TEXT NOT NULL UNIQUE,
        country TEXT NOT NULL CHECK(country IN ('England','Scotland','Wales','Northern Ireland'))
    );

    CREATE TABLE stations (
        station_id INTEGER PRIMARY KEY,
        region_id INTEGER NOT NULL,
        station_name TEXT NOT NULL,
        town TEXT NOT NULL,
        postcode_area TEXT NOT NULL,
        site_type TEXT NOT NULL CHECK(site_type IN ('Retail','Motorway','Car Park','Residential','Workplace')),
        opened_on TEXT NOT NULL,
        accessibility_rating TEXT NOT NULL
            CHECK(accessibility_rating IN ('Poor','Fair','Good','Excellent')),
        latitude REAL NOT NULL CHECK(latitude BETWEEN 49.8 AND 59.0),
        longitude REAL NOT NULL CHECK(longitude BETWEEN -8.5 AND 2.0),
        FOREIGN KEY(region_id) REFERENCES regions(region_id),
        UNIQUE(region_id, station_name)
    );

    CREATE TABLE chargers (
        charger_id INTEGER PRIMARY KEY,
        station_id INTEGER NOT NULL,
        charger_label TEXT NOT NULL,
        connector_type TEXT NOT NULL CHECK(connector_type IN ('CCS','CHAdeMO','Type 2')),
        max_power_kw REAL NOT NULL CHECK(max_power_kw > 0 AND max_power_kw <= 400),
        charger_status TEXT NOT NULL CHECK(charger_status IN ('Operational','Limited','Out of Service')),
        installation_year INTEGER NOT NULL CHECK(installation_year BETWEEN 2015 AND 2026),
        FOREIGN KEY(station_id) REFERENCES stations(station_id),
        UNIQUE(station_id, charger_label)
    );

    CREATE TABLE vehicles (
        vehicle_id INTEGER PRIMARY KEY,
        pseudonym TEXT NOT NULL UNIQUE,
        manufacturer TEXT NOT NULL,
        model TEXT NOT NULL,
        vehicle_segment TEXT NOT NULL CHECK(vehicle_segment IN ('Small','Family','SUV','Premium','Van')),
        battery_capacity_kwh REAL NOT NULL CHECK(battery_capacity_kwh BETWEEN 15 AND 150),
        model_year INTEGER CHECK(model_year BETWEEN 2017 AND 2026),
        battery_health_pct REAL NOT NULL CHECK(battery_health_pct BETWEEN 70 AND 100)
    );

    CREATE TABLE tariffs (
        region_id INTEGER NOT NULL,
        connector_type TEXT NOT NULL CHECK(connector_type IN ('CCS','CHAdeMO','Type 2')),
        tariff_period TEXT NOT NULL CHECK(tariff_period IN ('Peak','Off-Peak')),
        price_per_kwh_gbp REAL NOT NULL CHECK(price_per_kwh_gbp BETWEEN 0.05 AND 2.00),
        PRIMARY KEY(region_id, connector_type, tariff_period),
        FOREIGN KEY(region_id) REFERENCES regions(region_id)
    );

    CREATE TABLE charging_sessions (
        session_id INTEGER PRIMARY KEY,
        charger_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        started_at TEXT NOT NULL,
        ended_at TEXT NOT NULL,
        energy_kwh REAL NOT NULL CHECK(energy_kwh > 0 AND energy_kwh <= 160),
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes BETWEEN 1 AND 600),
        start_battery_pct REAL NOT NULL CHECK(start_battery_pct BETWEEN 0 AND 100),
        end_battery_pct REAL NOT NULL CHECK(end_battery_pct BETWEEN 0 AND 100),
        ambient_temp_c REAL NOT NULL CHECK(ambient_temp_c BETWEEN -15 AND 40),
        payment_method TEXT NOT NULL CHECK(payment_method IN ('Contactless','App','Subscription')),
        session_outcome TEXT NOT NULL CHECK(session_outcome IN ('Completed','Interrupted','Failed')),
        FOREIGN KEY(charger_id) REFERENCES chargers(charger_id),
        FOREIGN KEY(vehicle_id) REFERENCES vehicles(vehicle_id),
        CHECK(ended_at > started_at),
        CHECK(end_battery_pct >= start_battery_pct)
    );

    -- Composite primary key: one event sequence number per session.
    CREATE TABLE session_events (
        session_id INTEGER NOT NULL,
        event_sequence INTEGER NOT NULL CHECK(event_sequence >= 1),
        event_time TEXT NOT NULL,
        event_type TEXT NOT NULL CHECK(event_type IN ('Plugged In','Authentication','Charging Started','Charging Paused','Charging Resumed','Charging Completed','Unplugged','Fault')),
        event_note TEXT,
        PRIMARY KEY(session_id, event_sequence),
        FOREIGN KEY(session_id) REFERENCES charging_sessions(session_id)
    );

    -- Staging table intentionally has no uniqueness rule: it represents an imperfect
    -- external feed before validation and deduplication.
    CREATE TABLE raw_session_imports (
        import_row_id INTEGER PRIMARY KEY,
        source_session_ref TEXT NOT NULL,
        imported_at TEXT NOT NULL,
        raw_energy_kwh REAL,
        raw_payment_reference TEXT,
        quality_flag TEXT NOT NULL CHECK(quality_flag IN ('Clean','Missing field','Duplicate feed row'))
    );

    CREATE INDEX idx_sessions_started_at ON charging_sessions(started_at);
    CREATE INDEX idx_sessions_charger ON charging_sessions(charger_id);
    CREATE INDEX idx_sessions_vehicle ON charging_sessions(vehicle_id);
    CREATE INDEX idx_stations_region ON stations(region_id);
    """)

    regions = [
        ("London", "England"), ("South East", "England"), ("North West", "England"),
        ("West Midlands", "England"), ("Scotland", "Scotland"), ("Wales", "Wales"),
        ("East of England", "England"), ("Yorkshire", "England")
    ]
    cur.executemany("INSERT INTO regions(region_name,country) VALUES (?,?)", regions)

    towns = {
        "London": [("London","SW"),("London","E"),("London","N"),("London","SE")],
        "South East": [("Brighton","BN"),("Oxford","OX"),("Reading","RG"),("Guildford","GU")],
        "North West": [("Manchester","M"),("Liverpool","L"),("Preston","PR"),("Chester","CH")],
        "West Midlands": [("Birmingham","B"),("Coventry","CV"),("Wolverhampton","WV")],
        "Scotland": [("Glasgow","G"),("Edinburgh","EH"),("Dundee","DD"),("Perth","PH")],
        "Wales": [("Cardiff","CF"),("Swansea","SA"),("Newport","NP")],
        "East of England": [("Cambridge","CB"),("Norwich","NR"),("Luton","LU")],
        "Yorkshire": [("Leeds","LS"),("Sheffield","S"),("York","YO")]
    }
    station_ids = []
    for rid, (region, _) in enumerate(regions, start=1):
        for j in range(5):
            town, area = random.choice(towns[region])
            sid = (rid-1)*5+j+1
            station_ids.append(sid)
            opened = date(2018,1,1) + timedelta(days=random.randint(0, 3000))
            # Broad approximate UK coordinate ranges, generated for simulation only.
            lat = round(random.uniform(50.0, 58.5), 5)
            lon = round(random.uniform(-5.5, 1.5), 5)
            cur.execute("""INSERT INTO stations
                (region_id,station_name,town,postcode_area,site_type,opened_on,
                 accessibility_rating,latitude,longitude)
                 VALUES (?,?,?,?,?,?,?,?,?)""",
                (rid, f"{town} {random.choice(['Central','Retail Park','Travel Hub','West','East'])} {j+1}",
                 town, area, random.choice(["Retail","Motorway","Car Park","Residential","Workplace"]),
                 opened.isoformat(), choose_weighted([("Poor",5),("Fair",15),("Good",50),("Excellent",30)]),
                 lat, lon))

    charger_ids = []
    charger_details = {}
    for sid in station_ids:
        for c in range(4):
            cid = len(charger_ids)+1
            charger_ids.append(cid)
            connector = choose_weighted([("CCS",65),("Type 2",25),("CHAdeMO",10)])
            power = random.choice([7.4, 11, 22, 50, 75, 100, 150, 175, 300])
            status = choose_weighted([("Operational",91),("Limited",6),("Out of Service",3)])
            cur.execute("""INSERT INTO chargers
                (station_id,charger_label,connector_type,max_power_kw,charger_status,installation_year)
                VALUES (?,?,?,?,?,?)""",
                (sid, f"CP-{c+1:02d}", connector, power, status, random.randint(2017,2026)))
            charger_details[cid] = (sid, connector, power)

    makers = {
        "Tesla": [("Model 3","Family",60),("Model Y","SUV",75)],
        "Nissan": [("Leaf","Small",40),("Ariya","SUV",63)],
        "Kia": [("EV6","Family",77),("Niro EV","SUV",64)],
        "Hyundai": [("Kona Electric","Small",65),("IONIQ 5","Family",77)],
        "Volkswagen": [("ID.3","Small",58),("ID.4","SUV",77)],
        "BMW": [("i4","Premium",80),("iX1","Premium",65)],
        "MG": [("MG4","Small",64),("ZS EV","SUV",51)],
        "Renault": [("Zoe","Small",52),("Megane E-Tech","Family",60)],
        "Ford": [("Mustang Mach-E","SUV",75),("E-Transit","Van",68)]
    }
    vehicle_ids = []
    for i in range(350):
        maker = random.choice(list(makers))
        model, segment, base = random.choice(makers[maker])
        capacity = round(max(18, random.gauss(base, 4)), 1)
        model_year = random.randint(2018,2026)
        health = round(random.uniform(82,100) - max(0,2026-model_year)*0.7, 1)
        vid = i+1
        vehicle_ids.append(vid)
        # A small number of model_year values are genuinely unknown (NULL).
        if i in {17, 103, 288}:
            model_year = None
        cur.execute("""INSERT INTO vehicles
            (pseudonym,manufacturer,model,vehicle_segment,battery_capacity_kwh,model_year,battery_health_pct)
            VALUES (?,?,?,?,?,?,?)""",
            (f"EV-USER-{vid:04d}",maker,model,segment,capacity,model_year,health))

    tariff_rows = []
    for rid in range(1,9):
        for connector in ["CCS","CHAdeMO","Type 2"]:
            for period in ["Peak","Off-Peak"]:
                base = {"CCS":0.79,"CHAdeMO":0.75,"Type 2":0.55}[connector]
                regional_factor = random.uniform(0.92,1.10)
                peak_factor = 1.12 if period == "Peak" else 0.88
                price = round(base*regional_factor*peak_factor,3)
                tariff_rows.append((rid,connector,period,price))
    cur.executemany("INSERT INTO tariffs VALUES (?,?,?,?)", tariff_rows)

    start_date = datetime(2025,1,1)
    session_rows = []
    raw_rows = []
    for i in range(1,2001):
        cid = random.choice(charger_ids)
        sid, connector, power = charger_details[cid]
        vid = random.choice(vehicle_ids)
        start = start_date + timedelta(days=random.randint(0, 670),
                                       minutes=random.randint(0,1439))
        duration = max(8, min(300, int(random.lognormvariate(3.9,0.55))))
        energy = round(min(120, max(2.0, random.gauss(power*duration/60*0.62, 7))),2)
        energy = min(energy, 120)
        vehicle = cur.execute("SELECT battery_capacity_kwh FROM vehicles WHERE vehicle_id=?",(vid,)).fetchone()[0]
        start_batt = round(random.uniform(8,75),1)
        end_batt = round(min(100, start_batt + energy/vehicle*100),1)
        temp = round(max(-8,min(35,random.gauss(11,7))),1)
        outcome = choose_weighted([("Completed",91),("Interrupted",7),("Failed",2)])
        payment = random.choice(["Contactless","App","Subscription"])
        end = start + timedelta(minutes=duration)
        cur.execute("""INSERT INTO charging_sessions
            (charger_id,vehicle_id,started_at,ended_at,energy_kwh,duration_minutes,
             start_battery_pct,end_battery_pct,ambient_temp_c,payment_method,session_outcome)
             VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (cid,vid,start.isoformat(timespec="minutes"),end.isoformat(timespec="minutes"),
             energy,duration,start_batt,end_batt,temp,payment,outcome))
        session_rows.append((i, energy, start.isoformat(timespec="minutes")))
        # Realistic event sequences; failed/interrupted sessions may end with a fault/pause.
        event_types = ["Plugged In","Authentication","Charging Started"]
        if outcome == "Interrupted":
            event_types += ["Charging Paused","Unplugged"]
        elif outcome == "Failed":
            event_types += ["Fault","Unplugged"]
        else:
            event_types += ["Charging Completed","Unplugged"]
        event_time = start
        for seq, etype in enumerate(event_types, start=1):
            if seq > 1:
                event_time += timedelta(seconds=random.randint(20, max(30,duration*60//len(event_types))))
            note = None if random.random() < 0.35 else random.choice(
                ["Automated network event","User action recorded","Charger status update","Payment verified"])
            cur.execute("INSERT INTO session_events VALUES (?,?,?,?,?)",
                        (i,seq,event_time.isoformat(timespec="seconds"),etype,note))
        raw_ref = f"SRC-{i:06d}"
        raw_energy = energy
        flag = "Clean"
        if i % 97 == 0:  # Deliberately missing raw energy value in the staging feed.
            raw_energy = None
            flag = "Missing field"
        raw_rows.append((raw_ref,start.isoformat(timespec="seconds"),raw_energy,
                         None if i % 13 == 0 else f"PAY-{i:07d}",flag))

    cur.executemany("""INSERT INTO raw_session_imports
        (source_session_ref,imported_at,raw_energy_kwh,raw_payment_reference,quality_flag)
        VALUES (?,?,?,?,?)""", raw_rows)

    # Deliberately duplicate 12 source-feed rows to model at-least-once ingestion.
    for original in random.sample(raw_rows, 12):
        cur.execute("""INSERT INTO raw_session_imports
            (source_session_ref,imported_at,raw_energy_kwh,raw_payment_reference,quality_flag)
            VALUES (?,?,?,?,?)""",
            (original[0],original[1],original[2],original[3],"Duplicate feed row"))

    con.commit()
    # Assertions make the key assignment requirements testable.
    assert cur.execute("SELECT COUNT(*) FROM charging_sessions").fetchone()[0] >= 1000
    assert cur.execute("SELECT COUNT(*) FROM raw_session_imports").fetchone()[0] > 2000
    assert cur.execute("PRAGMA foreign_key_check").fetchall() == []
    con.close()
    return db_path

if __name__ == "__main__":
    path = build_database()
    print(f"Database created: {path}")
    with sqlite3.connect(path) as con:
        for table in ["regions","stations","chargers","vehicles","tariffs",
                      "charging_sessions","session_events","raw_session_imports"]:
            print(f"{table}: {con.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]} rows")
