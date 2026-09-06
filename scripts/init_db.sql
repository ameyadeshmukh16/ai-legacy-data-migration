CREATE TABLE IF NOT EXISTS departments (
 dept_id BIGSERIAL PRIMARY KEY, dept_cd VARCHAR(20) UNIQUE, dept_name VARCHAR(120),
 dept_typ_cd VARCHAR(3));
CREATE TABLE IF NOT EXISTS patient_records (
 pat_id BIGSERIAL PRIMARY KEY, first_name VARCHAR(80), last_name VARCHAR(80),
 pat_st_cd VARCHAR(2), admit_dt TIMESTAMP, discharge_dt TIMESTAMP,
 dob VARCHAR(10), blood_grp_cd VARCHAR(3), gndr_cd VARCHAR(1), ins_prvdr_cd VARCHAR(5));
CREATE TABLE IF NOT EXISTS doctors (
 doctor_id BIGSERIAL PRIMARY KEY, dept_id BIGINT NULL REFERENCES departments(dept_id),
 doc_nm VARCHAR(120), status_cd VARCHAR(2),
 spec_cd VARCHAR(5), qlf_cd VARCHAR(10));
CREATE TABLE IF NOT EXISTS appointments (
 appt_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 doctor_id BIGINT NULL REFERENCES doctors(doctor_id), appt_dt TIMESTAMP, appt_st INT,
 appt_typ_cd VARCHAR(3), cncl_rsn VARCHAR(255), pri_lvl INT);
CREATE TABLE IF NOT EXISTS billing (
 bill_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 bill_amt NUMERIC(12,2), bill_st VARCHAR(2), created_at TIMESTAMP,
 pay_mthd_cd VARCHAR(3), ins_clm_st VARCHAR(2), disc_pct NUMERIC(5,2));
CREATE TABLE IF NOT EXISTS med_records (
 med_record_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 doctor_id BIGINT NULL REFERENCES doctors(doctor_id), med_cd VARCHAR(20),
 dosage_txt VARCHAR(20), rte_cd VARCHAR(2), dur_days VARCHAR(20), prescribed_dt TIMESTAMP);
CREATE TABLE IF NOT EXISTS lab_orders (
 lab_order_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 doctor_id BIGINT NULL REFERENCES doctors(doctor_id), tst_cd VARCHAR(10),
 tst_st_cd VARCHAR(2), rslt_txt VARCHAR(255), urgcy_cd VARCHAR(3), ordered_dt TIMESTAMP);
CREATE TABLE IF NOT EXISTS ward_alloc (
 ward_alloc_id BIGSERIAL PRIMARY KEY, pat_id BIGINT NULL REFERENCES patient_records(pat_id),
 ward_cd VARCHAR(5), bed_no VARCHAR(6), alloc_st VARCHAR(1), alloc_dt VARCHAR(10));

INSERT INTO departments(dept_cd,dept_name,dept_typ_cd) VALUES
 ('CARD','Cardiology','IPD'),('ORTH','Orthopedics','IPD')
ON CONFLICT (dept_cd) DO NOTHING;
INSERT INTO patient_records(first_name,last_name,pat_st_cd,admit_dt,dob,blood_grp_cd,gndr_cd,ins_prvdr_cd)
SELECT 'Demo','Patient','A',CURRENT_TIMESTAMP,'01-01-1990','OP','M','INS01'
WHERE NOT EXISTS (SELECT 1 FROM patient_records WHERE first_name='Demo' AND last_name='Patient');
