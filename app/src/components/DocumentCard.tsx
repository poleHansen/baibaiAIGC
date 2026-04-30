import type { DocumentStatus } from "../types/app";

type Props = {
  value: DocumentStatus | null;
  busy: boolean;
  stopBusy: boolean;
  onPickFile: () => void;
  onRunRound: () => void;
  onStop: () => void;
  pickerLabel?: string;
  progressStatusLabel: string;
};

function displayDocId(status: DocumentStatus): string {
  const normalizedDocId = status.docId.replace(/\\/g, "/");
  if (normalizedDocId.includes("/")) {
    const segments = normalizedDocId.split("/").filter(Boolean);
    return segments[segments.length - 1] ?? status.docId;
  }
  return status.docId;
}

function renderResumeStatus(status: DocumentStatus): string {
  if (!status.hasNextRound || status.isComplete) {
    return "当前文档已完成全部轮次。";
  }
  if (status.totalChunkCount > 0 && status.completedChunkCount > 0) {
    return `检测到断点进度：已完成 ${status.completedChunkCount}/${status.totalChunkCount} 块，可继续执行。`;
  }
  return "当前轮还没有已保存的分块进度。";
}

export function DocumentCard({
  value,
  busy,
  stopBusy,
  onPickFile,
  onRunRound,
  onStop,
  pickerLabel = "选择文档",
  progressStatusLabel,
}: Props) {
  const canRunNextRound = Boolean(value?.hasNextRound) && !busy;
  const canStop = Boolean(value?.hasNextRound) && busy && !stopBusy;

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
          <div className="info-grid">
            <div className="info-item">
              <span>断点进度</span>
              <strong>{value.totalChunkCount ? `${value.completedChunkCount}/${value.totalChunkCount}` : "暂无"}</strong>
            </div>
            <div className="info-item">
              <span>进度状态</span>
              <strong>{progressStatusLabel}</strong>
            </div>
          </div>
          <div className="path-box">
            <span>当前输入</span>
            <strong>{value.currentInputPath}</strong>
          </div>
          <div className="path-box">
            <span>续跑说明</span>
            <strong>{renderResumeStatus(value)}</strong>
          </div>
          {value.lastError ? (
            <div className="path-box">
              <span>暂停原因</span>
              <strong>{value.lastError}</strong>
            </div>
          ) : null}
          {value.stopReason ? (
            <div className="path-box">
              <span>停止说明</span>
              <strong>{value.stopReason}</strong>
            </div>
          ) : null}
          <div className="button-row">
            <button className="primary-button" onClick={onRunRound} disabled={!canRunNextRound}>
              {value.progressStatus === "paused" || value.progressStatus === "stopped"
                ? "继续执行当前轮"
                : value.hasNextRound
                  ? "执行下一轮"
                  : "已完成全部轮次"}
            </button>
            <button className="secondary-button" onClick={onStop} disabled={!canStop}>
              {stopBusy || value.stopRequested ? "停止中..." : "停止当前轮"}
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
