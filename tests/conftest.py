import pytest

from classroom.web.app import create_app


@pytest.fixture
def app(tmp_path):
    instance = create_app(tmp_path / "data", bootstrap_key="test-bootstrap")
    instance.config["TESTING"] = True
    yield instance
    instance.extensions['diagnostics'].close()
    for handler in list(instance.logger.handlers):
        if hasattr(handler, "baseFilename"):
            instance.logger.removeHandler(handler)
            handler.close()


@pytest.fixture
def services(app):
    return app.extensions["classes"], app.extensions["seating"]


@pytest.fixture
def active(services):
    classes, seating = services
    cls = classes.create("高一（3）班")
    data = seating.open_round(cls["id"])
    return cls, data["round"]
