import os
import sys
import unittest

PATH = os.path.dirname(os.path.realpath(__file__))
sys.path.append(PATH + "/../")
sys.path.append(PATH + "/minqlx-plugin-tests/src/main/python")
sys.path.append(PATH + "/minqlx-plugin-tests/src/unittest/python")

from .test_balance import TestBalance
from .test_teamplay import TestTeamplay

def suite():
    r = unittest.TestSuite()
    r.addTest(TestBalance())
    r.addTest(TestTeamplay())
    return r


if __name__ == '__main__':
    runner = unittest.TextTestRunner()
    runner.run(suite())
