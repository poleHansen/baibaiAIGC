import type { DocumentStatus } from "../types/app";

type Props = {
  value: DocumentStatus | null;
  busy: boolean;
  onPickFile: () => void;
  onRunRound: () => void;
  onPauseRound: () => void;
  canPause: boolean;
  pickerLabel?: string;
};

function displayDocId(status: DocumentStatus): string {
  const normalizedDocId = status.docId.replace(/\\/g, "/");
  if (normalizedDocId.includes("/")) {
    const segments = normalizedDocId.split("/").filter(Boolean);
    return segments[segments.length - 1] ?? status.docId;
  }
  return status.docId;
}

export function DocumentCard({ value, busy, onPickFile, onRunRound, onPauseRound, canPause, pickerLabel = "选择文档" }: Props) {
  const canRunNextRound = Boolean(value?.hasNextRound) && !busy;

  return (
    <section className="glass-card section-stack">
      <div className="section-header">
        <div>
          <h2>文档工作台</h2>
          <p>支持 txt 与 Word。上传 Word 后会先自动提取为中间 txt。</p>
        </div>
        <button className="secondary-button" onClick={onPickFile} disabled={busy}>
          {pickerLabel}
        </button>
      </div>
      {value ? (
        <>
          <div className="info-grid">
            <div className="info-item">
              <span>文档标识</span>
              <strong>{displayDocId(value)}</strong>
            </div>
            <div className="info-item">
              <span>文件类型</span>
              <strong>{value.sourceKind}</strong>
            </div>
            <div className="info-item">
              <span>已完成轮次</span>
              <strong>{value.completedRounds.length ? value.completedRounds.join(" / ") : "暂无"}</strong>
            </div>
            <div className="info-item">
              <span>下一轮</span>
              <strong>{value.hasNextRound && value.nextRound ? `第 ${value.nextRound} 轮` : "已完成全部轮次"}</strong>
            </div>
          </div>
          <div className="path-box">
            <span>当前输入</span>
            <strong>{value.currentInputPath}</strong>
          </div>
          <div className="button-column">
            <button className="primary-button" onClick={onRunRound} disabled={!canRunNextRound}>
              {value.hasNextRound ? "执行下一轮" : "已完成全部轮次"}
            </button>
            <button className="secondary-button" onClick={onPauseRound} disabled={!canPause}>
              暂停并存档
            </button>
          </div>
        </>
      ) : (
        <div className="empty-state">
          <strong>还没有导入文档</strong>
          <p>先选择一个 txt 或 docx 文件，系统会自动读取当前轮次状态。</p>
        </div>
      )}
    </section>
  );
}
