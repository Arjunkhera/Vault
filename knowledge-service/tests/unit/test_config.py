"""Tests for config/settings.py (Story 005)."""

import os
import tempfile
from pathlib import Path
import yaml
import pytest

from src.config.settings import VaultSettings, load_settings, DEFAULT_CONFIG_PATH


class TestVaultSettingsDefaults:
    """Test default values in VaultSettings."""
    
    def test_default_port(self):
        settings = VaultSettings()
        assert settings.port == 8000

    def test_default_host(self):
        settings = VaultSettings()
        assert settings.host == "0.0.0.0"

    def test_default_knowledge_repo_path(self):
        settings = VaultSettings()
        assert settings.knowledge_repo_path == "/data/knowledge-repo"

    def test_default_workspace_path(self):
        settings = VaultSettings()
        assert settings.workspace_path == "/workspace"

    def test_default_qmd_index_name(self):
        settings = VaultSettings()
        assert settings.qmd_index_name == "knowledge"

    def test_default_sync_interval(self):
        settings = VaultSettings()
        assert settings.sync_interval == 300

    def test_default_log_level(self):
        settings = VaultSettings()
        assert settings.log_level == "info"


class TestLoadSettingsDefaults:
    """Test load_settings with no config file or env vars."""
    
    def test_default_settings_no_config(self, tmp_path, monkeypatch):
        """Default settings work without any config file or env vars."""
        # Use a nonexistent path to ensure no config file is loaded
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.port == 8000
        assert settings.host == "0.0.0.0"
        assert settings.knowledge_repo_path == "/data/knowledge-repo"
        assert sources['port'] == 'default'
        assert sources['host'] == 'default'

    def test_all_sources_recorded(self, tmp_path):
        """All fields have a source recorded."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        expected_fields = [
            "knowledge_repo_path",
            "workspace_path",
            "qmd_index_name",
            "sync_interval",
            "port",
            "host",
            "log_level",
        ]
        for field in expected_fields:
            assert field in sources
            assert sources[field] is not None


class TestEnvVarOverride:
    """Test environment variable overrides."""
    
    def test_env_var_knowledge_repo_path(self, tmp_path, monkeypatch):
        """KNOWLEDGE_REPO_PATH env var overrides default."""
        monkeypatch.setenv('KNOWLEDGE_REPO_PATH', '/test/repo/path')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.knowledge_repo_path == '/test/repo/path'
        assert 'env:KNOWLEDGE_REPO_PATH' in sources['knowledge_repo_path']

    def test_env_var_port(self, tmp_path, monkeypatch):
        """VAULT_PORT env var overrides default."""
        monkeypatch.setenv('VAULT_PORT', '9999')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.port == 9999
        assert 'env:VAULT_PORT' in sources['port']

    def test_env_var_host(self, tmp_path, monkeypatch):
        """VAULT_HOST env var overrides default."""
        monkeypatch.setenv('VAULT_HOST', 'localhost')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.host == 'localhost'
        assert 'env:VAULT_HOST' in sources['host']

    def test_env_var_log_level(self, tmp_path, monkeypatch):
        """VAULT_LOG_LEVEL env var overrides default."""
        monkeypatch.setenv('VAULT_LOG_LEVEL', 'debug')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.log_level == 'debug'
        assert 'env:VAULT_LOG_LEVEL' in sources['log_level']

    def test_env_var_sync_interval(self, tmp_path, monkeypatch):
        """SYNC_INTERVAL env var overrides default."""
        monkeypatch.setenv('SYNC_INTERVAL', '600')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings.sync_interval == 600
        assert 'env:SYNC_INTERVAL' in sources['sync_interval']

    def test_invalid_env_var_type(self, tmp_path, monkeypatch):
        """Invalid env var values are logged but don't crash."""
        monkeypatch.setenv('VAULT_PORT', 'not-a-number')
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        # Should fall back to default
        assert settings.port == 8000
        assert sources['port'] == 'default'


class TestConfigFileLoading:
    """Test config file loading."""
    
    def test_config_file_loaded(self, tmp_path):
        """Config file values are loaded."""
        config = tmp_path / "config.yaml"
        config.write_text("port: 9999\nhost: localhost\nlog_level: debug")
        
        settings, sources = load_settings(config_path=config)
        
        assert settings.port == 9999
        assert settings.host == 'localhost'
        assert settings.log_level == 'debug'
        assert f'config:{config}' in sources['port']

    def test_config_file_knowledge_repo_path(self, tmp_path):
        """Config file can set knowledge_repo_path."""
        config = tmp_path / "config.yaml"
        config.write_text("knowledge_repo_path: /custom/repo")
        
        settings, sources = load_settings(config_path=config)
        
        assert settings.knowledge_repo_path == '/custom/repo'

    def test_config_file_with_all_fields(self, tmp_path):
        """Config file with all fields."""
        config = tmp_path / "config.yaml"
        config.write_text("""
port: 9999
host: 127.0.0.1
knowledge_repo_path: /custom/repo
workspace_path: /custom/workspace
qmd_index_name: custom_index
sync_interval: 600
log_level: debug
""")
        
        settings, sources = load_settings(config_path=config)
        
        assert settings.port == 9999
        assert settings.host == '127.0.0.1'
        assert settings.knowledge_repo_path == '/custom/repo'
        assert settings.workspace_path == '/custom/workspace'
        assert settings.qmd_index_name == 'custom_index'
        assert settings.sync_interval == 600
        assert settings.log_level == 'debug'

    def test_missing_config_file_ok(self, tmp_path):
        """Missing config file doesn't raise an error."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        assert settings is not None
        assert settings.port == 8000

    def test_invalid_yaml_config(self, tmp_path):
        """Invalid YAML in config file falls back gracefully."""
        config = tmp_path / "config.yaml"
        config.write_text("invalid: yaml: content: [")
        
        settings, sources = load_settings(config_path=config)
        
        # Should fall back to defaults
        assert settings.port == 8000
        assert settings.host == "0.0.0.0"

    def test_invalid_field_value_in_config(self, tmp_path):
        """Invalid field value in config file is skipped."""
        config = tmp_path / "config.yaml"
        config.write_text("""
port: not-a-number
host: localhost
""")
        
        settings, sources = load_settings(config_path=config)
        
        # port should fall back to default
        assert settings.port == 8000
        # host should be set from config
        assert settings.host == 'localhost'


class TestPrecedenceChain:
    """Test the precedence chain: CLI > env vars > config file > defaults."""
    
    def test_env_overrides_config(self, tmp_path, monkeypatch):
        """Env vars override config file values."""
        config = tmp_path / "config.yaml"
        config.write_text("port: 9999\nhost: confighost")
        
        monkeypatch.setenv('VAULT_HOST', 'envhost')
        settings, sources = load_settings(config_path=config)
        
        # port from config
        assert settings.port == 9999
        # host from env (overrides config)
        assert settings.host == 'envhost'
        assert 'env:VAULT_HOST' in sources['host']

    def test_cli_overrides_env(self, tmp_path, monkeypatch):
        """CLI args override env vars."""
        monkeypatch.setenv('KNOWLEDGE_REPO_PATH', '/from/env')
        config_path = tmp_path / "nonexistent.yaml"
        
        settings, sources = load_settings(
            config_path=config_path,
            cli_overrides={'knowledge_repo_path': '/from/cli'}
        )
        
        assert settings.knowledge_repo_path == '/from/cli'
        assert sources['knowledge_repo_path'] == 'cli'

    def test_cli_overrides_config(self, tmp_path):
        """CLI args override config file values."""
        config = tmp_path / "config.yaml"
        config.write_text("port: 9999\nhost: confighost")
        
        settings, sources = load_settings(
            config_path=config,
            cli_overrides={'port': 7777, 'host': 'clihost'}
        )
        
        assert settings.port == 7777
        assert settings.host == 'clihost'
        assert sources['port'] == 'cli'
        assert sources['host'] == 'cli'

    def test_full_precedence_chain(self, tmp_path, monkeypatch):
        """Test full precedence chain with all layers."""
        config = tmp_path / "config.yaml"
        config.write_text("""
port: 9999
host: confighost
log_level: config_level
""")
        
        # Set env vars for some fields
        monkeypatch.setenv('VAULT_HOST', 'envhost')
        monkeypatch.setenv('VAULT_LOG_LEVEL', 'env_level')
        
        # CLI overrides for some fields
        settings, sources = load_settings(
            config_path=config,
            cli_overrides={'port': 7777}
        )
        
        # port: cli > config
        assert settings.port == 7777
        assert sources['port'] == 'cli'
        
        # host: env > config
        assert settings.host == 'envhost'
        assert 'env:VAULT_HOST' in sources['host']
        
        # log_level: env > config
        assert settings.log_level == 'env_level'
        assert 'env:VAULT_LOG_LEVEL' in sources['log_level']


class TestCliOverrides:
    """Test CLI override handling."""
    
    def test_cli_single_override(self, tmp_path):
        """CLI overrides single field."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(
            config_path=config_path,
            cli_overrides={'port': 5555}
        )
        
        assert settings.port == 5555
        assert sources['port'] == 'cli'

    def test_cli_multiple_overrides(self, tmp_path):
        """CLI overrides multiple fields."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(
            config_path=config_path,
            cli_overrides={
                'port': 5555,
                'host': 'clihost',
                'log_level': 'debug'
            }
        )
        
        assert settings.port == 5555
        assert settings.host == 'clihost'
        assert settings.log_level == 'debug'

    def test_cli_none_values_ignored(self, tmp_path, monkeypatch):
        """CLI overrides with None values are ignored."""
        monkeypatch.setenv('VAULT_PORT', '9999')
        config_path = tmp_path / "nonexistent.yaml"
        
        settings, sources = load_settings(
            config_path=config_path,
            cli_overrides={'port': None}
        )
        
        # Should use env var value
        assert settings.port == 9999

    def test_cli_unknown_field_ignored(self, tmp_path):
        """CLI overrides for unknown fields are ignored."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(
            config_path=config_path,
            cli_overrides={'unknown_field': 'value', 'port': 5555}
        )
        
        # unknown_field is ignored
        assert not hasattr(settings, 'unknown_field')
        # port is set
        assert settings.port == 5555


class TestLogSources:
    """Test the log_sources method."""
    
    def test_log_sources_with_defaults(self, tmp_path, caplog):
        """log_sources correctly identifies default sources."""
        config_path = tmp_path / "nonexistent.yaml"
        settings, sources = load_settings(config_path=config_path)
        
        # Should be able to call log_sources without error
        settings.log_sources(sources)
        
        # Check that sources dict has all expected fields
        expected_fields = [
            "knowledge_repo_path",
            "workspace_path",
            "qmd_index_name",
            "sync_interval",
            "port",
            "host",
            "log_level",
        ]
        for field in expected_fields:
            assert field in sources
            assert "default" in sources[field]

    def test_log_sources_with_config(self, tmp_path, caplog):
        """log_sources correctly identifies config file sources."""
        config = tmp_path / "config.yaml"
        config.write_text("port: 9999")
        
        settings, sources = load_settings(config_path=config)
        settings.log_sources(sources)
        
        assert f'config:{config}' in sources['port']
        assert 'default' in sources['host']


class TestComplexScenarios:
    """Test complex real-world scenarios."""
    
    def test_dev_environment_config(self, tmp_path, monkeypatch):
        """Typical dev environment setup."""
        config = tmp_path / "config.yaml"
        config.write_text("""
port: 8001
host: localhost
log_level: debug
""")
        
        monkeypatch.setenv('KNOWLEDGE_REPO_PATH', os.path.expanduser('~/vault-data'))
        
        settings, sources = load_settings(config_path=config)
        
        assert settings.port == 8001
        assert settings.host == 'localhost'
        assert settings.log_level == 'debug'
        assert settings.knowledge_repo_path == os.path.expanduser('~/vault-data')

    def test_production_environment_config(self, tmp_path, monkeypatch):
        """Typical production environment setup with env vars."""
        # Config file has some defaults
        config = tmp_path / "config.yaml"
        config.write_text("log_level: info")
        
        # Prod env vars override
        monkeypatch.setenv('KNOWLEDGE_REPO_PATH', '/mnt/storage/knowledge')
        monkeypatch.setenv('VAULT_PORT', '80')
        monkeypatch.setenv('VAULT_HOST', '0.0.0.0')
        
        settings, sources = load_settings(config_path=config)
        
        assert settings.knowledge_repo_path == '/mnt/storage/knowledge'
        assert settings.port == 80
        assert settings.host == '0.0.0.0'
        assert settings.log_level == 'info'
