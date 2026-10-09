import pytest

from reelstudio import db


@pytest.fixture()
def session():
    db.init_db("sqlite://")
    with db.session_scope() as s:
        yield s
