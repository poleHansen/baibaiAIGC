import type { ChangeEvent } from "react";
import type { ModelConfig } from "../types/app";

type Props = {
  value: ModelConfig;
  busy: boolean;
  platformMode?: boolean;
  availableModels: string[];
  onChange: (value: ModelConfig) => void;
  onFetchModels: () => void;
  onSave: () => void;
  onTestConnection: () => void;
};

export function ModelConfigCard({ value, busy, platformMode = false, availableModels, onChange, onFetchModels, onSave, onTestConnection }: Props) {
  function handleTextField<K extends keyof ModelConfig>(key: K) {
    return (event: ChangeEvent<HTMLInputElement>) => {
      const nextValue = key === "temperature" ? Number(event.target.value) : event.target.value;
      onChange({ ...value, [key]: nextValue });
    };
  }

  function handleOfflineModeChange(event: ChangeEvent<HTMLInputElement>) {
    onChange({ ...value, offlineMode: event.target.checked });
  }

  return (
    <section className="glass-card section-stack">
      <div className="section-header">
        <div>
          <h2>模型设置</h2>
          <p>{platformMode ? "平台已统一配置模型，此页仅供查看。" : "本地保存模型配置，供每一轮处理直接调用。"}</p>
        </div>
      </div>
      <label className="field">
        <span>接口地址</span>
        <input
          value={value.baseUrl}
          onChange={handleTextField("baseUrl")}
          placeholder="https://your-endpoint/v1"
          disabled={platformMode}
        />
      </label>
      <label className="field">
        <span>API Key</span>
        <input
          type="password"
          value={value.apiKey}
          onChange={handleTextField("apiKey")}
          placeholder={platformMode ? "由平台统一管理" : "请输入 API Key"}
          disabled={platformMode}
        />
      </label>
      <label className="field">
        <span>模型名称</span>
        <div className="model-input-row">
          <input
            value={value.model}
            onChange={handleTextField("model")}
            placeholder="provider/模型名，例如 openai/gpt-4.1-mini"
            disabled={platformMode}
          />
          <button className="secondary-button" onClick={onFetchModels} disabled={busy || platformMode}>
            获取模型列表
          </button>
        </div>
      </label>
      {availableModels.length > 0 ? (
        <label className="field">
          <span>从列表选择模型</span>
          <select
            value={value.model}
            onChange={(event) => onChange({ ...value, model: event.target.value })}
            disabled={platformMode}
          >
            <option value="">请选择模型</option>
            {availableModels.map((model) => (
              <option key={model} value={model}>{model}</option>
            ))}
          </select>
        </label>
      ) : null}
      <label className="field">
        <span>Temperature</span>
        <input
          type="number"
          min="0"
          max="2"
          step="0.1"
          value={value.temperature}
          onChange={handleTextField("temperature")}
          disabled={platformMode}
        />
      </label>
      <label className="toggle-field">
        <span>离线联调模式</span>
        <input type="checkbox" checked={value.offlineMode} onChange={handleOfflineModeChange} disabled={platformMode} />
      </label>
      <div className="button-row">
        <button className="secondary-button" onClick={onTestConnection} disabled={busy || platformMode}>
          测试连通性
        </button>
        <button className="primary-button" onClick={onSave} disabled={busy || platformMode}>
          保存模型设置
        </button>
      </div>
    </section>
  );
}
