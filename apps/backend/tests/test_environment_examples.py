import json
from pathlib import Path

from super_ai.project_config import load_project_config

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_local_project_configs_are_ignored_and_templates_are_sanitized() -> None:
    ignore_patterns = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "config/project.json" in ignore_patterns
    assert "config/user.project.json" in ignore_patterns

    base_template = json.loads(
        (REPO_ROOT / "config/project.template.json").read_text(encoding="utf-8")
    )
    user_template = json.loads(
        (REPO_ROOT / "config/user.project.template.json").read_text(encoding="utf-8")
    )

    assert base_template["llm"]["apiKey"] == ""
    assert base_template["llm"]["embedding"]["apiKey"] == ""
    assert base_template["llm"]["embedding"]["baseUrl"] == ""
    assert base_template["llm"]["embedding"]["model"] == ""
    assert base_template["llm"]["embedding"]["dimensions"] is None
    assert base_template["llm"]["rerank"]["apiKey"] == ""
    assert base_template["llm"]["rerank"]["baseUrl"] == ""
    assert base_template["llm"]["rerank"]["model"] == ""
    assert base_template["clsMcpServer"]["secretId"] == ""
    assert base_template["clsMcpServer"]["secretKey"] == ""
    assert base_template["prometheusAlerts"]["sources"][0]["password"] == ""
    assert base_template["aiopsDemo"]["password"] == ""
    assert base_template["minio"]["accessKey"] == ""
    assert base_template["minio"]["secretKey"] == ""
    assert base_template["langfuse"]["enabled"] is False
    assert base_template["langfuse"]["publicKey"] == ""
    assert base_template["langfuse"]["secretKey"] == ""
    assert base_template["langfuse"]["host"] == "https://cloud.langfuse.com"
    assert user_template["llm"]["apiKey"] == ""
    assert user_template["llm"]["embedding"]["apiKey"] == ""
    assert user_template["llm"]["embedding"]["baseUrl"] == ""
    assert user_template["llm"]["embedding"]["model"] == ""
    assert user_template["llm"]["embedding"]["dimensions"] is None
    assert user_template["llm"]["rerank"]["apiKey"] == ""
    assert user_template["llm"]["rerank"]["baseUrl"] == ""
    assert user_template["llm"]["rerank"]["model"] == ""
    assert user_template["clsMcpServer"]["secretId"] == ""
    assert user_template["clsMcpServer"]["secretKey"] == ""
    assert user_template["langfuse"]["publicKey"] == ""
    assert user_template["langfuse"]["secretKey"] == ""


def test_project_config_contains_development_provider_config(tmp_path: Path) -> None:
    base_config = json.loads(
        (REPO_ROOT / "config/project.template.json").read_text(encoding="utf-8")
    )
    user_config = json.loads(
        (REPO_ROOT / "config/user.project.template.json").read_text(encoding="utf-8")
    )
    # Exercise merging with synthetic credentials, independently of the operator's files.
    user_config["llm"]["apiKey"] = "test-provider-key"
    path = tmp_path / "project.json"
    path.write_text(json.dumps(base_config), encoding="utf-8")
    path.with_name("user.project.json").write_text(json.dumps(user_config), encoding="utf-8")
    merged_config = load_project_config(path)
    llm = merged_config["llm"]

    assert base_config["llm"]["apiKey"] == ""
    assert base_config["llm"]["chatModel"] == ""
    assert base_config["llm"]["embeddingModel"] == ""
    assert base_config["clsMcpServer"]["secretId"] == ""
    assert base_config["clsMcpServer"]["secretKey"] == ""
    assert base_config["clsLogUpload"]["region"] == ""
    assert base_config["clsLogUpload"]["logsetId"] == ""
    assert base_config["clsLogUpload"]["topicId"] == ""
    assert llm["apiKey"] == "test-provider-key"
    assert llm["baseUrl"] == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert llm["chatModel"] == "qwen3.7-max"
    assert llm["embeddingModel"] == "text-embedding-v4"
    assert llm["embeddingDimensions"] == 1024
    assert llm["rerankModel"] == "qwen3-vl-rerank"
    assert llm["embedding"] == {
        "apiKey": "",
        "baseUrl": "",
        "model": "",
        "dimensions": None,
    }
    assert llm["rerank"] == {"apiKey": "", "baseUrl": "", "model": ""}
    assert "modelCapabilities" not in base_config["llm"]
    capabilities = user_config["llm"]["modelCapabilities"]
    assert capabilities["qwen3.7-max"]["contextWindowTokens"] == 1_000_000
    assert llm["maxRetries"] == 2


def test_project_config_declares_real_prometheus_and_alertmanager_sources(tmp_path: Path) -> None:
    config = json.loads(
        (REPO_ROOT / "config/project.template.json").read_text(encoding="utf-8")
    )
    sources = config["prometheusAlerts"]["sources"]

    assert sources[0]["type"] == "prometheus-v1"
    assert sources[0]["alertsApi"] == ""
    assert sources[1]["type"] == "alertmanager-v2"
    assert sources[1]["alertsApi"] == "http://127.0.0.1:9093/api/v2/alerts"
    path = tmp_path / "project.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    configured_sources = [
        {**sources[0], "alertsApi": "https://prometheus.example.test/api/v1/alerts"},
        sources[1],
    ]
    path.with_name("user.project.json").write_text(
        json.dumps({"prometheusAlerts": {"sources": configured_sources}}), encoding="utf-8"
    )
    merged = load_project_config(path)
    assert merged["prometheusAlerts"]["sources"] == configured_sources
