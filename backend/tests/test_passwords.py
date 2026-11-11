from pathlib import Path

from app.core import passwords
from app.core.passwords import password_problem


def test_common_password():
    assert password_problem("password12") == "password_common"
    assert password_problem("PASSWORD12") == "password_common"


def test_matches_username_case_insensitive():
    assert password_problem("Jane_Doe12", username="jane_doe12") == "password_matches_identity"


def test_matches_email_and_local_part():
    assert password_problem("Zebra-Quartz-77", email="zebra-quartz-77@example.com") == "password_matches_identity"
    assert password_problem("Zebra-Quartz-77", email="ZEBRA-QUARTZ-77") == "password_matches_identity"


def test_too_short():
    assert password_problem("a1b2c3d4e") == "password_too_short"


def test_too_long():
    assert password_problem("x" * 129) == "password_too_long"


def test_ok():
    assert password_problem("correct horse battery") is None


def test_boundaries():
    assert password_problem("Qv9!zk3#Lm") is None  # exactly 10
    assert password_problem("Qv9!zk3#Lm" + "x" * 118) is None  # exactly 128


def test_list_file_size():
    path = Path(passwords.__file__).parent / "data" / "common_passwords.txt"
    assert len(path.read_text().splitlines()) >= 9900
