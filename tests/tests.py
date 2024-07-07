import os


def test_cwd():
    # test that the current working directory is in "mytest"
    assert os.getcwd().endswith("mytest")
