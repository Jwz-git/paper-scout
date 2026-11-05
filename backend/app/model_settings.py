"""本机模型配置：入口校验、私有文件保存与空闲时应用。"""
import json
import os
import tempfile
from pathlib import Path
from typing import Dict, List, Literal, Optional
from uuid import uuid4
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator, model_validator

from backend.app.adapters.llm import create_llm_adapter
from backend.app.dialogue import TURN_SECONDS
from backend.app.domain.models import Run
from backend.app.storage.database import StateConflict


class ModelConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    base_url: str = Field(max_length=2000)
    model: str = Field(max_length=200)
    api_key: Optional[SecretStr] = None  # null / 省略：保留服务端现有密钥。
    clear_api_key: bool = Field(default=False, strict=True)

    @field_validator("base_url", "model")
    @classmethod
    def trim_text(cls, value):
        return value.strip()

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value):
        if not value:
            return value
        try:
            url = urlsplit(value)
            valid = url.scheme in ("http", "https") and bool(url.hostname) and url.port != 0 and not any(character.isspace() for character in value)
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("服务地址必须是有效的 HTTP 或 HTTPS 地址")
        if url.username is not None or url.password is not None or url.query or url.fragment:
            raise ValueError("服务地址不能包含凭据、查询参数或片段；密钥请填入独立字段")
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def validate_key(cls, value):
        if value is not None:
            key = value.get_secret_value()
            if len(key) > 4096 or any(character.isspace() for character in key):
                raise ValueError("密钥不能包含空白字符且不能超过 4096 字符")
        return value

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.clear_api_key and self.api_key is not None and self.api_key.get_secret_value():
            raise ValueError("替换密钥与清除密钥不能同时操作")
        return self


class ModelSettings(ModelConnection):
    enabled: bool = Field(strict=True)

    @model_validator(mode="after")
    def require_enabled_fields(self):
        if self.enabled and (not self.base_url or not self.model):
            raise ValueError("启用模型时必须填写服务地址和模型名称")
        return self


class StoredProfile(ModelConnection):
    id: str
    name: str


class CompleteConnection(ModelConnection):
    @model_validator(mode="after")
    def require_fields(self):
        if not self.base_url or not self.model:
            raise ValueError("模型配置必须填写服务地址和模型名称")
        return self


class LegacyStoredSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    active_profile_id: Optional[str]
    profiles: List[StoredProfile]

    @model_validator(mode="after")
    def valid_selection(self):
        ids = [profile.id for profile in self.profiles]
        if len(set(ids)) != len(ids) or (self.active_profile_id is not None and self.active_profile_id not in ids):
            raise ValueError("模型配置标识或当前选择无效")
        if self.enabled:
            profile = next((p for p in self.profiles if p.id == self.active_profile_id), None)
            if profile is None or not profile.base_url or not profile.model:
                raise ValueError("启用模型需要完整的当前配置")
        return self



def clean_models(values):
    values = [value.strip() for value in values]
    if any(not value or len(value) > 200 for value in values):
        raise ValueError("模型 ID 必须为1–200字符")
    return list(dict.fromkeys(values))


class ProviderConnection(ModelConnection):
    model: str = ""

    @model_validator(mode="after")
    def require_address(self):
        if not self.base_url:
            raise ValueError("请先填写服务地址")
        return self


class ProviderUpdate(ProviderConnection):
    name: str = Field(default="", max_length=80)
    models: List[str] = Field(min_length=1, max_length=100)
    _clean_models = field_validator("models")(clean_models)


class StoredProvider(ModelConnection):
    model: str = ""
    id: str
    name: str
    models: List[str]
    _clean_models = field_validator("models")(clean_models)


class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool
    active_provider_id: Optional[str]
    active_model: Optional[str]
    providers: List[StoredProvider]

    @model_validator(mode="after")
    def valid_selection(self):
        ids = [provider.id for provider in self.providers]
        if len(ids) != len(set(ids)) or (self.active_provider_id is not None and self.active_provider_id not in ids):
            raise ValueError("供应商标识或当前选择无效")
        if self.enabled:
            provider = next((p for p in self.providers if p.id == self.active_provider_id), None)
            if provider is None or not provider.base_url or self.active_model not in provider.models:
                raise ValueError("当前模型不属于所选供应商")
        return self


class ModelCatalogRequest(ProviderConnection):
    provider_id: Optional[str] = None
    cursor: Optional[str] = Field(default=None, min_length=1, max_length=200)


class ModelSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    provider_id: str = Field(min_length=1)
    model: str = Field(min_length=1, max_length=200)


class ProviderView(BaseModel):
    id: str
    name: str
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    base_url: str
    models: List[str]
    api_key_set: bool


class ModelSettingsView(BaseModel):
    enabled: bool
    protocol: Literal["openai_chat", "openai_responses", "anthropic_messages"]
    base_url: str
    model: str
    api_key_set: bool
    source: Literal["environment", "local"]
    busy: bool
    active_provider_id: Optional[str]
    active_model: Optional[str]
    providers: List[ProviderView]
    limits: Dict[str, Dict[str, int]]
    app_name: str
    app_version: str


class ProviderSaveResult(BaseModel):
    provider_id: str
    settings: ModelSettingsView


# 实际生效的执行上限：研究取运行模型的默认值，对话每轮固定一次模型调用。
EFFECTIVE_LIMITS = {
    "research": {name: int(Run.model_fields[name].default) for name in ("max_rounds", "max_calls", "max_seconds")},
    "conversation": {"calls_per_turn": 1, "seconds_per_turn": int(TURN_SECONDS)},
}


class ModelSettingsService:
    def __init__(self, config):
        self.path = config.data_dir / "model-settings.json"
        self.source = "environment"
        self.app_name, self.app_version = config.app_name, config.app_version
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # 旧版文件保存过从未生效的 limits，读取时丢弃。
                    data.pop("limits", None)
                if isinstance(data, dict) and "providers" in data:
                    self.state = ProviderSettings.model_validate(data)
                elif isinstance(data, dict) and "profiles" in data:
                    self.state = self.migrate_profiles(LegacyStoredSettings.model_validate(data))
                else:
                    self.state = self.from_single(ModelSettings.model_validate(data))
            except (OSError, ValueError):
                raise RuntimeError("无法读取本地AI服务设置，请检查数据目录中的模型设置文件") from None
            self.source = "local"
        else:
            try:
                cfg = ModelSettings(enabled=bool(config.llm_base_url or config.llm_model or config.llm_api_key.get_secret_value()),
                                    protocol=config.llm_protocol, base_url=config.llm_base_url, model=config.llm_model, api_key=config.llm_api_key)
                self.state = self.from_single(cfg)
            except ValidationError:
                raise RuntimeError("模型配置无效，请检查 LLM_BASE_URL、LLM_MODEL 和 LLM_API_KEY") from None

    @staticmethod
    def from_single(cfg):
        if not cfg.base_url and not cfg.model and not (cfg.api_key and cfg.api_key.get_secret_value()):
            return ProviderSettings(enabled=False, active_provider_id=None, active_model=None, providers=[])
        provider = StoredProvider(id="default", name=urlsplit(cfg.base_url).hostname or "默认供应商",
                                  protocol=cfg.protocol, base_url=cfg.base_url, models=[cfg.model] if cfg.model else [], api_key=cfg.api_key)
        return ProviderSettings(enabled=cfg.enabled, active_provider_id=provider.id, active_model=cfg.model or None, providers=[provider])

    @staticmethod
    def migrate_profiles(legacy):
        # 只合并地址、协议、凭据均相同的已知旧配置；不同密钥保持独立供应商。
        providers, groups, profile_providers = [], {}, {}
        for profile in legacy.profiles:
            if not profile.base_url and not profile.model and not (profile.api_key and profile.api_key.get_secret_value()):
                continue
            identity = (profile.protocol, profile.base_url, profile.api_key.get_secret_value() if profile.api_key else "")
            provider = groups.get(identity)
            if provider is None:
                name = profile.name
                if name.endswith(" · " + profile.model):
                    name = name[:-(len(profile.model) + 3)]
                if name == profile.model or not name:
                    name = urlsplit(profile.base_url).hostname or "供应商"
                provider = StoredProvider(id=profile.id, name=name, protocol=profile.protocol, base_url=profile.base_url,
                                          models=[], api_key=profile.api_key)
                groups[identity] = provider
                providers.append(provider)
            if profile.model and profile.model not in provider.models:
                provider.models.append(profile.model)
            profile_providers[profile.id] = provider.id
        active = next((p for p in legacy.profiles if p.id == legacy.active_profile_id), None)
        return ProviderSettings(enabled=legacy.enabled, active_provider_id=profile_providers.get(legacy.active_profile_id),
                                active_model=active.model if active and active.model else None, providers=providers)

    def find(self, provider_id):
        provider = next((p for p in self.state.providers if p.id == provider_id), None)
        if provider is None:
            raise KeyError("供应商不存在")
        return provider

    @property
    def current(self):
        provider = self.find(self.state.active_provider_id) if self.state.active_provider_id else None
        return ModelSettings(enabled=self.state.enabled, protocol=provider.protocol, base_url=provider.base_url,
                             model=self.state.active_model or "", api_key=provider.api_key) if provider else ModelSettings(enabled=False, protocol="openai_chat", base_url="", model="")

    def adapter(self):
        cfg = self.current
        return create_llm_adapter(cfg.protocol, cfg.base_url, cfg.model, cfg.api_key.get_secret_value() if cfg.api_key else "") if cfg.enabled else None
    @staticmethod
    def busy(db, worker):
        if worker is not None and worker.busy:
            return True
        with db._get_connection() as connection:
            return bool(connection.execute(
                "SELECT 1 FROM conversation_turns WHERE status IN ('queued','processing') LIMIT 1"
            ).fetchone() or connection.execute(
                "SELECT 1 FROM runs WHERE status IN ('queued','running','pause_requested') LIMIT 1"
            ).fetchone())

    def require_idle(self, db, worker):
        if self.busy(db, worker):
            raise StateConflict("仍有排队或执行中的工作，请暂停研究并等待当前对话结束后再切换当前模型")

    @staticmethod
    def resolve_key(update, previous):
        old_key = previous.api_key or SecretStr("") if previous else SecretStr("")
        if previous and update.base_url != previous.base_url and old_key.get_secret_value() and update.api_key is None and not update.clear_api_key:
            raise ValueError("更改服务地址时，请重新输入密钥或明确清除已保存的密钥")
        return SecretStr("") if update.clear_api_key else (update.api_key if update.api_key is not None else old_key)


    def view(self, db, worker):
        cfg = self.current
        return {"enabled": cfg.enabled, "protocol": cfg.protocol, "base_url": cfg.base_url, "model": cfg.model,
                "api_key_set": bool(cfg.api_key and cfg.api_key.get_secret_value()), "source": self.source,
                "busy": self.busy(db, worker), "active_provider_id": self.state.active_provider_id,
                "active_model": self.state.active_model,
                "providers": [{"id": p.id, "name": p.name, "protocol": p.protocol, "base_url": p.base_url,
                               "models": p.models, "api_key_set": bool(p.api_key and p.api_key.get_secret_value())} for p in self.state.providers],
                "limits": EFFECTIVE_LIMITS, "app_name": self.app_name, "app_version": self.app_version}

    def commit(self, state, engine, dialogue, apply):
        provider = next((p for p in state.providers if p.id == state.active_provider_id), None)
        adapter = create_llm_adapter(provider.protocol, provider.base_url, state.active_model, provider.api_key.get_secret_value() if provider.api_key else "") if apply and state.enabled else None
        payload = state.model_dump(exclude={"providers"})
        payload["providers"] = [{**p.model_dump(exclude={"model", "api_key", "clear_api_key"}),
                                 "api_key": p.api_key.get_secret_value() if p.api_key else ""} for p in state.providers]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.state, self.source = state, "local"
        if apply:
            engine.llm = adapter
            dialogue.llm = adapter

    def save_provider(self, update, provider_id, db, worker, engine, dialogue):
        previous = self.find(provider_id) if provider_id is not None else None
        active = bool(self.state.enabled and previous and previous.id == self.state.active_provider_id)
        if active:
            self.require_idle(db, worker)
        key = self.resolve_key(update, previous)
        provider = StoredProvider(id=previous.id if previous else "provider_"+uuid4().hex,
                                  name=update.name.strip() or urlsplit(update.base_url).hostname,
                                  protocol=update.protocol, base_url=update.base_url, models=update.models, api_key=key)
        providers = [provider if p.id == provider.id else p for p in self.state.providers]
        if previous is None:
            providers.append(provider)
        removed_current = active and self.state.active_model not in provider.models
        state = ProviderSettings(enabled=False if removed_current else self.state.enabled,
                                 active_provider_id=None if removed_current else self.state.active_provider_id,
                                 active_model=None if removed_current else self.state.active_model,
                                 providers=providers)
        self.commit(state, engine, dialogue, active)
        return {"provider_id": provider.id, "settings": self.view(db, worker)}

    def select_model(self, update, db, worker, engine, dialogue):
        provider = self.find(update.provider_id)
        if update.model not in provider.models:
            raise ValueError("模型不在此供应商的已选模型中")
        self.require_idle(db, worker)
        state = self.state.model_copy(update={"enabled": True, "active_provider_id": provider.id, "active_model": update.model})
        self.commit(state, engine, dialogue, True)
        return self.view(db, worker)

    def delete_provider(self, provider_id, db, worker, engine, dialogue):
        self.find(provider_id)
        active = provider_id == self.state.active_provider_id
        if active:
            self.require_idle(db, worker)
        state = self.state.model_copy(update={"providers": [p for p in self.state.providers if p.id != provider_id],
                    **({"enabled": False, "active_provider_id": None, "active_model": None} if active else {})})
        self.commit(state, engine, dialogue, active)
        return self.view(db, worker)

    async def list_models(self, update):
        from backend.app.adapters.model_catalog import list_models
        previous = self.find(update.provider_id) if update.provider_id is not None else None
        key = self.resolve_key(update, previous)
        return await list_models(update.base_url, update.protocol, key.get_secret_value(), update.cursor)

    def save(self, update, db, worker, engine, dialogue):
        # 保留已发布的单模型设置入口；更新当前供应商，不拆出一份供应商凭据。
        self.require_idle(db, worker)
        previous = self.find(self.state.active_provider_id) if self.state.active_provider_id else None
        key = self.resolve_key(update, previous)
        models = [update.model] + [m for m in previous.models if m not in (update.model, self.state.active_model)] if previous else [update.model]
        provider = StoredProvider(id=previous.id if previous else "default", name=previous.name if previous else urlsplit(update.base_url).hostname or "默认供应商",
                                  protocol=update.protocol, base_url=update.base_url, models=[m for m in models if m], api_key=key)
        providers = [p for p in self.state.providers if p.id != provider.id] + [provider]
        state = ProviderSettings(enabled=update.enabled, active_provider_id=provider.id, active_model=update.model or None, providers=providers)
        self.commit(state, engine, dialogue, True)
        return self.view(db, worker)
