import random
from datetime import timedelta
from faker import Faker
from sqlalchemy import create_engine, text
from config.settings import settings

fake = Faker()
BATCH_SIZE = 500

DEPT_TYPES = ["IPD", "OPD", "ICU", "ER", "SRG"]
BLOOD_GROUPS = ["AP", "AN", "BP", "BN", "OP", "ON", "ABP", "ABN"]
GENDERS = ["M", "F", "U"]
INSURERS = [f"INS{n:02d}" for n in range(1, 13)]
SPECIALTIES = ["CARD", "ORTH", "NEUR", "PEDS", "ONCO"]
QUALIFICATIONS = ["MBBS", "MD", "MS", "DM", "MCH"]
DOCTOR_STATUS = ["A", "I"]
PATIENT_STATUS = ["A", "D", "I", "S"]
APPT_TYPES = ["NEW", "FLW", "EMR", "REV"]
CANCEL_REASONS = ["Patient no-show", "Doctor unavailable", "Rescheduled", "Weather", "Emergency"]
BILL_STATUS = ["PD", "UP", "PP", "WO"]
PAY_METHODS = ["CSH", "INS", "CRD", "UPI"]
CLAIM_STATUS = ["PN", "AP", "RJ", "PP"]
MED_CODES = [f"MED{n:03d}" for n in range(1, 41)]
DOSAGES = ["1x2", "1x3", "BD", "TDS", "SOS", "OD", "QID"]
ROUTES = ["OR", "IV", "IM", "SC"]
DUR_DAYS_MESSY = ["5", "7", "10", "14", "7 days", "10 days", "one week", "two weeks", "5d"]
LAB_TESTS = ["CBC", "LFT", "KFT", "TSH", "XRAY", "MRI", "ECG", "USG"]
LAB_STATUS = ["OR", "PR", "CM", "CN"]
URGENCY = ["ROU", "URG", "STT"]
WARD_CODES = ["G1", "G2", "ICU", "PVTW", "SRG"]
ALLOC_STATUS = ["A", "V", "M", "B"]


def _dob():
    dob = fake.date_of_birth(minimum_age=1, maximum_age=95)
    if random.random() < 0.5:
        return dob.strftime("%d-%m-%Y")
    return dob.strftime("%Y-%m-%d")


def _maybe_null(value, null_rate):
    return None if random.random() < null_rate else value


def _insert_batches(engine, table, columns, rows):
    if not rows:
        return
    cols = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    stmt = text(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})")
    with engine.begin() as conn:
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            conn.execute(stmt, [dict(zip(columns, r)) for r in batch])
    print(f"  inserted {len(rows)} rows into {table}")


def seed_departments(engine, n=12):
    rows = []
    codes_used = {"CARD", "ORTH"}
    for _ in range(n - 2):
        cd = fake.unique.lexify(text="DEP???").upper()
        codes_used.add(cd)
        rows.append((cd, fake.company()[:120], random.choice(DEPT_TYPES)))
    _insert_batches(engine, "departments", ["dept_cd", "dept_name", "dept_typ_cd"], rows)


def seed_doctors(engine, n=150):
    with engine.connect() as conn:
        dept_ids = [r[0] for r in conn.execute(text("SELECT dept_id FROM departments"))]
    rows = []
    for _ in range(n):
        rows.append((
            _maybe_null(random.choice(dept_ids), 0.03),
            fake.name()[:120],
            random.choice(DOCTOR_STATUS),
            random.choice(SPECIALTIES),
            random.choice(QUALIFICATIONS),
        ))
    _insert_batches(engine, "doctors", ["dept_id", "doc_nm", "status_cd", "spec_cd", "qlf_cd"], rows)


def seed_patients(engine, n=12000):
    rows = []
    for _ in range(n):
        admit = fake.date_time_between(start_date="-3y", end_date="now")
        discharge = admit + timedelta(days=random.randint(0, 21)) if random.random() < 0.7 else None
        rows.append((
            fake.first_name()[:80],
            fake.last_name()[:80],
            _maybe_null(random.choice(PATIENT_STATUS), 0.02),
            admit,
            discharge,
            _dob(),
            random.choice(BLOOD_GROUPS),
            random.choice(GENDERS),
            _maybe_null(random.choice(INSURERS), 0.04),
        ))
    _insert_batches(engine, "patient_records",
        ["first_name", "last_name", "pat_st_cd", "admit_dt", "discharge_dt", "dob", "blood_grp_cd", "gndr_cd", "ins_prvdr_cd"],
        rows)


def seed_appointments(engine, n=15000):
    with engine.connect() as conn:
        pat_ids = [r[0] for r in conn.execute(text("SELECT pat_id FROM patient_records"))]
        doc_ids = [r[0] for r in conn.execute(text("SELECT doctor_id FROM doctors"))]
    rows = []
    for _ in range(n):
        cancelled = random.random() < 0.15
        rows.append((
            _maybe_null(random.choice(pat_ids), 0.04),
            _maybe_null(random.choice(doc_ids), 0.04),
            fake.date_time_between(start_date="-2y", end_date="+30d"),
            _maybe_null(random.randint(1, 5), 0.02),
            random.choice(APPT_TYPES),
            random.choice(CANCEL_REASONS) if cancelled else None,
            random.randint(1, 5),
        ))
    _insert_batches(engine, "appointments",
        ["pat_id", "doctor_id", "appt_dt", "appt_st", "appt_typ_cd", "cncl_rsn", "pri_lvl"],
        rows)


def seed_billing(engine, n=13000):
    with engine.connect() as conn:
        pat_ids = [r[0] for r in conn.execute(text("SELECT pat_id FROM patient_records"))]
    rows = []
    for _ in range(n):
        rows.append((
            _maybe_null(random.choice(pat_ids), 0.03),
            round(random.uniform(50, 25000), 2),
            random.choice(BILL_STATUS),
            fake.date_time_between(start_date="-2y", end_date="now"),
            random.choice(PAY_METHODS),
            random.choice(CLAIM_STATUS),
            _maybe_null(round(random.uniform(0, 30), 2), 0.6),
        ))
    _insert_batches(engine, "billing",
        ["pat_id", "bill_amt", "bill_st", "created_at", "pay_mthd_cd", "ins_clm_st", "disc_pct"],
        rows)


def seed_med_records(engine, n=20000):
    with engine.connect() as conn:
        pat_ids = [r[0] for r in conn.execute(text("SELECT pat_id FROM patient_records"))]
        doc_ids = [r[0] for r in conn.execute(text("SELECT doctor_id FROM doctors"))]
    rows = []
    for _ in range(n):
        rows.append((
            _maybe_null(random.choice(pat_ids), 0.03),
            _maybe_null(random.choice(doc_ids), 0.03),
            random.choice(MED_CODES),
            random.choice(DOSAGES),
            random.choice(ROUTES),
            random.choice(DUR_DAYS_MESSY),
            fake.date_time_between(start_date="-2y", end_date="now"),
        ))
    _insert_batches(engine, "med_records",
        ["pat_id", "doctor_id", "med_cd", "dosage_txt", "rte_cd", "dur_days", "prescribed_dt"],
        rows)


def seed_lab_orders(engine, n=18000):
    with engine.connect() as conn:
        pat_ids = [r[0] for r in conn.execute(text("SELECT pat_id FROM patient_records"))]
        doc_ids = [r[0] for r in conn.execute(text("SELECT doctor_id FROM doctors"))]
    rows = []
    for _ in range(n):
        status = random.choice(LAB_STATUS)
        result = fake.sentence(nb_words=6) if status == "CM" and random.random() > 0.3 else None
        rows.append((
            _maybe_null(random.choice(pat_ids), 0.03),
            _maybe_null(random.choice(doc_ids), 0.03),
            random.choice(LAB_TESTS),
            status,
            result,
            random.choice(URGENCY),
            fake.date_time_between(start_date="-2y", end_date="now"),
        ))
    _insert_batches(engine, "lab_orders",
        ["pat_id", "doctor_id", "tst_cd", "tst_st_cd", "rslt_txt", "urgcy_cd", "ordered_dt"],
        rows)


def seed_ward_alloc(engine, n=8000):
    with engine.connect() as conn:
        pat_ids = [r[0] for r in conn.execute(text("SELECT pat_id FROM patient_records"))]
    rows = []
    for _ in range(n):
        alloc_dt = fake.date_between(start_date="-2y", end_date="now")
        alloc_dt_str = alloc_dt.strftime("%d-%m-%Y") if random.random() < 0.5 else alloc_dt.strftime("%Y-%m-%d")
        rows.append((
            _maybe_null(random.choice(pat_ids), 0.03),
            random.choice(WARD_CODES),
            f"{random.randint(100, 399)}{random.choice('ABCD')}",
            random.choice(ALLOC_STATUS),
            alloc_dt_str,
        ))
    _insert_batches(engine, "ward_alloc",
        ["pat_id", "ward_cd", "bed_no", "alloc_st", "alloc_dt"],
        rows)


def main():
    engine = create_engine(settings.source_db_url)
    print("Seeding departments...")
    seed_departments(engine)
    print("Seeding doctors...")
    seed_doctors(engine)
    print("Seeding patient_records...")
    seed_patients(engine)
    print("Seeding appointments...")
    seed_appointments(engine)
    print("Seeding billing...")
    seed_billing(engine)
    print("Seeding med_records...")
    seed_med_records(engine)
    print("Seeding lab_orders...")
    seed_lab_orders(engine)
    print("Seeding ward_alloc...")
    seed_ward_alloc(engine)
    print("Done.")


if __name__ == "__main__":
    main()
