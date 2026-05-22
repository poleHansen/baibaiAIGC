type Props = {
  inputText: string;
  outputText: string;
  busy: boolean;
  onInputChange: (text: string) => void;
  onReduce: () => void;
  onCopy: () => void;
};

export function TextReduceCard({
  inputText,
  outputText,
  busy,
  onInputChange,
  onReduce,
  onCopy,
}: Props) {
  const canReduce = inputText.trim().length > 0 && !busy;
  const canCopy = outputText.length > 0 && !busy;

  return (
    <section className="glass-card section-stack">
      <div className="section-header">
        <div>
          <h2>直接粘贴降AIGC</h2>
          <p>粘贴已知的AI生成段落，经过两轮降重处理后直接输出结果。</p>
        </div>
      </div>

      <div className="field">
        <span>输入文本</span>
        <textarea
          value={inputText}
          onChange={(e) => onInputChange(e.target.value)}
          placeholder="在此粘贴需要降AIGC的文本内容..."
          disabled={busy}
          rows={10}
          style={{
            width: "100%",
            border: "1px solid rgba(60, 60, 67, 0.12)",
            background: "rgba(255, 255, 255, 0.9)",
            padding: "12px 14px",
            borderRadius: "14px",
            outline: "none",
            resize: "vertical",
            font: "inherit",
            fontSize: "13px",
            lineHeight: "1.6",
          }}
        />
      </div>

      <div className="button-row">
        <button className="primary-button" onClick={onReduce} disabled={!canReduce}>
          {busy ? "处理中..." : "开始降AIGC"}
        </button>
      </div>

      {outputText ? (
        <div className="field">
          <span>处理结果</span>
          <textarea
            value={outputText}
            readOnly
            rows={10}
            style={{
              width: "100%",
              border: "1px solid rgba(52, 199, 89, 0.28)",
              background: "rgba(240, 247, 255, 0.96)",
              padding: "12px 14px",
              borderRadius: "14px",
              outline: "none",
              resize: "vertical",
              font: "inherit",
              fontSize: "13px",
              lineHeight: "1.6",
              color: "#1d1d1f",
            }}
          />
          <div className="button-row" style={{ marginTop: "8px" }}>
            <button className="secondary-button" onClick={onCopy} disabled={!canCopy}>
              复制结果
            </button>
          </div>
        </div>
      ) : null}
    </section>
  );
}
