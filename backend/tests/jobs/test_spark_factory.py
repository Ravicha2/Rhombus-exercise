from django.test import TestCase
from jobs.spark import get_spark_session


class SparkSessionFactoryTest(TestCase):

    def test_singleton_returns_same_instance(self):
        session1 = get_spark_session()
        session2 = get_spark_session()
        self.assertIs(session1, session2)

    def test_session_configured_for_local_mode(self):
        session = get_spark_session()
        self.assertIn("local", session.conf.get("spark.master"))