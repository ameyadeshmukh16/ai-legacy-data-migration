CREATE TABLE IF NOT EXISTS departments (
 dept_id BIGSERIAL PRIMARY KEY, dept_cd VARCHAR(20) UNIQUE, dept_name VARCHAR(120));
CREATE TABLE IF NOT EXISTS patient_records (
 pat_id BIGSERIAL PRIMARY KEY, first_name VARCHAR(80), last_name VARCHAR(80),
 pat_st_cd VARCHAR(2), admit_dt TIMESTAMP, discharge_dt TIMESTAMP);
CREATE TABLE IF NOT EXISTS doctors (
 doctor_id BIGSERIAL PRIMARY KEY, dept_id BIGINT NULL REFERENCES departments(dept_id),
 doc_nm VARCHAR(120), status_cd VARCHAR(2));
CREATE TABLE IF NOT EXISTS appointments (
 appt_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 doctor_id BIGINT NULL REFERENCES doctors(doctor_id), appt_dt TIMESTAMP, appt_st INT);
CREATE TABLE IF NOT EXISTS billing (
 bill_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 bill_amt NUMERIC(12,2), bill_st VARCHAR(2), created_at TIMESTAMP);
INSERT INTO departments(dept_cd,dept_name) VALUES ('CARD','Cardiology'),('ORTH','Orthopedics')
ON CONFLICT (dept_cd) DO NOTHING;
INSERT INTO patient_records(first_name,last_name,pat_st_cd,admit_dt)
SELECT 'Demo','Patient','A',CURRENT_TIMESTAMP
WHERE NOT EXISTS (SELECT 1 FROM patient_records WHERE first_name='Demo' AND last_name='Patient');
