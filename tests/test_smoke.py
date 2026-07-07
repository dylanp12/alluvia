import alluvia


def test_package_imports_and_has_version():
    assert isinstance(alluvia.__version__, str)
