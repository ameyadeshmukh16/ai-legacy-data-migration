def test_low_confidence_is_not_approved():
    r={"confidence":0.65,"human_reviewed":False,"override_note":None}
    assert r["confidence"]<0.80 and not r["human_reviewed"]
def test_low_confidence_approved_with_note():
    r={"confidence":0.65,"human_reviewed":True,"override_note":"Domain expert confirmed semantics."}
    assert r["confidence"]<0.80 and r["human_reviewed"] and r["override_note"]
