import type { ChangeEvent } from "react";
import type { ModelConfig } from "../types/app";

type Props = {
  value: ModelConfig;
  busy: boolean;
  onChange: (value: ModelConfig) => void;
  onSave: () => void;
  onTestConnection: () => void;
};

export function ModelConfigCard({ value, busy, onChange, onSave, onTestConnection }: Props) {
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
          <p>本地保存模型配置，供每一轮处理直接调用。</p>
        </div>
      </div>
      <label className="field">
        <span>接口地址</span>
        <input
          value={value.baseUrl}
          onChange={handleTextField("baseUrl")}
          placeholder="https://your-endpoint/v1"
        />
      </label>
      <label className="field">
        <span>API Key</span>
        <input
          type="password"
          value={value.apiKey}
          onChange={handleTextField("apiKey")}
          placeholder="请输入 API Key"
        />
      </label>
      <label className="field">
        <span>模型名称</span>
        <input
          value={value.model}
          onChange={handleTextField("model")}
          placeholder="例如 gpt-4.1-mini"
        />
      </label>
      <label className="field">
        <span>接口类型</span>
        <select
          value={value.apiType}
          onChange={(event) => onChange({
            ...value,
            apiType: event.target.value as ModelConfig["apiType"],
          })}
        >
          <option value="chat_completions">chat/completions</option>
          <option value="responses">responses</option>
        </select>
      </label>
      <label className="field">
        <span>Temperature</span>
        <input
          type="number"
          min="0"
          max="2"
          step="0.1"
          value={value.temperature}
          onChange={handleTextField("temperature")}
        />
      </label>
      <label className="toggle-field">
        <span>离线联调模式</span>
        <input type="checkbox" checked={value.offlineMode} onChange={handleOfflineModeChange} />
      </label>
      <div className="button-row">
        <button className="secondary-button" onClick={onTestConnection} disabled={busy}>
          测试连通性
        </button>
        <button className="primary-button" onClick={onSave} disabled={busy}>
          保存模型设置
        </button>
      </div>
    </section>
  );
}
