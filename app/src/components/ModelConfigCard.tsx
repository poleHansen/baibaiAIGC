import type { ChangeEvent } from "react";
import type { ApiMode, ModelConfig, PromptProfile } from "../types/app";

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

  function handlePromptProfileChange(promptProfile: PromptProfile) {
    onChange({ ...value, promptProfile });
  }

  function handleApiModeChange(event: ChangeEvent<HTMLSelectElement>) {
    onChange({ ...value, apiMode: event.target.value as ApiMode });
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
        <span>接口模式</span>
        <select value={value.apiMode} onChange={handleApiModeChange}>
          <option value="responses">/v1/responses</option>
          <option value="chat-completions">/v1/chat/completions</option>
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
      <div className="field">
        <span>去 AI 模式</span>
        <div className="segmented-control" role="group" aria-label="去 AI 模式">
          <button
            type="button"
            className={value.promptProfile === "cn" ? "segment-button active" : "segment-button"}
            onClick={() => handlePromptProfileChange("cn")}
          >
            中文两轮
          </button>
          <button
            type="button"
            className={value.promptProfile === "en" ? "segment-button active" : "segment-button"}
            onClick={() => handlePromptProfileChange("en")}
          >
            英文单轮
          </button>
        </div>
      </div>
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
