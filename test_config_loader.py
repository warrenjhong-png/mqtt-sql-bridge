import tempfile
import unittest
from pathlib import Path

from config_loader import ConfigLoader


class ConfigLoaderTests(unittest.TestCase):
    def test_loads_dispatch_x_and_y_settings(self):
        config_text = """
mqtt:
  broker: localhost
  topics: []
db:
  server: localhost
  database: test
  username: user
  password: password
dispatch:
  enabled: true
  factory_code: zhongli-A8
  system_type: TecoS1
  dispatch_x:
    enabled: true
    url: http://host.docker.internal/SICApi/sic/GetDispatch?dispatchName=X&command=PieceId
  dispatch_y:
    enabled: false
    url: http://host.docker.internal/SICApi/sic/GetDispatch?dispatchName=Y&command=PieceId
"""
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            mapping_path = Path(directory) / "field_mapping.yaml"
            config_path.write_text(config_text, encoding="utf-8")
            mapping_path.write_text("{}", encoding="utf-8")

            config, _ = ConfigLoader(
                str(config_path), str(mapping_path)
            ).load()

        self.assertTrue(config.dispatch.dispatch_x.enabled)
        self.assertIn("dispatchName=X", config.dispatch.dispatch_x.url)
        self.assertFalse(config.dispatch.dispatch_y.enabled)
        self.assertIn("DispatchY", config.dispatch.dispatch_y.url)


if __name__ == "__main__":
    unittest.main()
