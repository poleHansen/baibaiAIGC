import type { ActivePreview } from "../hooks/useAppState";
import type { RoundResult } from "../types/app";

type Props = {
  result: RoundResult | null;
  activePreview: ActivePreview | null;
  nextRound: number | null;
  selectedParagraphIndexes: number[];
  busy: boolean;
  onToggleParagraph: (paragraphIndex: number) => void;
  onSelectAllParagraphs: () => void;
  onClearParagraphs: () => void;
  onCreateRevision: () => void;
  onRunNextPartial: () => void;
  onExportTxt: () => void;
  onExportDocx: () => void;
};

function formatPreviewLabel(preview: ActivePreview): string {
  if (preview.kind === "streaming") {
    const suffix = preview.streamingInterrupted ? "已中断" : "生成中";
    return preview.revisionNumber
      ? `第 ${preview.round} 轮 / 修订 ${preview.revisionNumber} · ${suffix}`
      : `第 ${preview.round} 轮 · ${suffix}`;
  }
  if (preview.kind === "current-result") {
    return preview.revisionNumber ? `第 ${preview.round} 轮 / 修订 ${preview.revisionNumber}` : `第 ${preview.round} 轮最新结果`;
  }
  if (preview.kind === "round" && preview.round === 0) {
    return "初始预览";
  }
  if (preview.revisionNumber) {
    return `第 ${preview.round} 轮 / 修订 ${preview.revisionNumber}`;
  }
  return `第 ${preview.round} 轮`;
}

export function ResultCard({
  result,
  activePreview,
  nextRound,
  selectedParagraphIndexes,
  busy,
  onToggleParagraph,
  onSelectAllParagraphs,
  onClearParagraphs,
  onCreateRevision,
  onRunNextPartial,
  onExportTxt,
  onExportDocx,
}: Props) {
  const pausedError = typeof result?.docEntry?.last_error === "string" ? result.docEntry.last_error : "";
  const paragraphCount = activePreview?.preview.paragraphs.length ?? 0;
  const selectedCount = selectedParagraphIndexes.length;
  // 运行中的增量预览：段落会一段段追加进来，此时不允许选择/导出（输出文件还没生成）。
  const isStreaming = activePreview?.kind === "streaming";
  const streamingPending = activePreview?.pendingParagraphCount ?? 0;
  const streamingTotal = paragraphCount + streamingPending;
  const streamingPercent = streamingTotal > 0 ? Math.round((paragraphCount / streamingTotal) * 100) : 0;
  const canRunSelection = Boolean(activePreview && selectedCount > 0 && !busy && !isStreaming);
  const canCreateRevision = canRunSelection && !(activePreview?.kind === "round" && activePreview.round === 0);
  const canRunNextPartial = canRunSelection && activePreview?.round !== undefined && activePreview.round + 1 === nextRound;

  return (
    <section className="glass-card section-stack result-card">
      <div className="section-header">
        <div>
          <h2>预览</h2>
          <p>支持按段落选择后生成当前轮修订版，或只在下一轮处理选中段落；新导入文档也可直接从预览开始。</p>
        </div>
        {activePreview ? <span className="pill">{formatPreviewLabel(activePreview)}</span> : null}
      </div>
      {activePreview ? (
        <>
          {isStreaming ? (
            <div className={`stream-progress ${activePreview.streamingInterrupted ? "is-interrupted" : ""}`}>
              <div className="stream-progress-track">
                <span className="stream-progress-fill" style={{ width: `${streamingPercent}%` }} />
              </div>
              <p className="stream-progress-text">
                {activePreview.streamingInterrupted
                  ? `本轮已中断，已生成 ${paragraphCount}/${streamingTotal} 段，已完成的内容保留在预览里。`
                  : `已完成 ${paragraphCount}/${streamingTotal} 段，处理完一段就追加一段，不用等整份文件。`}
              </p>
            </div>
          ) : null}
          <div className="info-grid compact">
            <div className="info-item">
              <span>预览来源</span>
              <strong>{activePreview.label}</strong>
            </div>
            <div className="info-item">
              <span>段落数</span>
              <strong>{paragraphCount}</strong>
            </div>
            <div className="info-item">
              <span>已选段落</span>
              <strong>{selectedCount}</strong>
            </div>
            {result ? (
              <div className="info-item">
                <span>块数</span>
                <strong>{result.outputSegmentCount}</strong>
              </div>
            ) : null}
            {pausedError ? (
              <div className="info-item">
                <span>最近暂停原因</span>
                <strong>{pausedError}</strong>
              </div>
            ) : null}
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={onSelectAllParagraphs} disabled={busy || isStreaming || !paragraphCount}>
              全选段落
            </button>
            <button className="secondary-button" onClick={onClearParagraphs} disabled={busy || isStreaming || !selectedCount}>
              清空选择
            </button>
            <button className="secondary-button" onClick={onCreateRevision} disabled={!canCreateRevision}>
              在当前轮生成修订版
            </button>
            <button className="primary-button" onClick={onRunNextPartial} disabled={!canRunNextPartial}>
              在下一轮处理所选段落
            </button>
          </div>
          {isStreaming && paragraphCount === 0 ? (
            <div className="empty-state stream-empty-state">
              <strong>第 1 段正在生成</strong>
              <p>处理完一段就会追加到这里，可以一直盯着进度，不用等整份文件跑完。</p>
            </div>
          ) : null}
          <div className="paragraph-preview-list">
            {activePreview.preview.paragraphs.map((paragraph) => {
              const checked = selectedParagraphIndexes.includes(paragraph.paragraphIndex);
              return (
                <label
                  key={`${activePreview.outputPath}-${paragraph.paragraphIndex}`}
                  className={`paragraph-preview-item ${checked ? "selected" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => onToggleParagraph(paragraph.paragraphIndex)}
                    disabled={busy || isStreaming}
                  />
                  <div className="paragraph-preview-content">
                    <div className="paragraph-preview-head">
                      <strong>第 {paragraph.paragraphIndex + 1} 段</strong>
                      <span>{paragraph.chunkCount} 块</span>
                    </div>
                    <p>{paragraph.text || "当前段落为空"}</p>
                  </div>
                </label>
              );
            })}
            {isStreaming && paragraphCount > 0 && !activePreview.streamingInterrupted ? (
              <div className="paragraph-preview-item stream-placeholder">
                <span className="stream-dot" aria-hidden="true" />
                <div className="paragraph-preview-content">
                  <div className="paragraph-preview-head">
                    <strong>第 {paragraphCount + 1} 段</strong>
                    <span>生成中…</span>
                  </div>
                  <p>正在调用模型，完成后立即追加到这里。</p>
                </div>
              </div>
            ) : null}
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={onExportTxt} disabled={busy || isStreaming}>
              导出 TXT
            </button>
            <button className="primary-button" onClick={onExportDocx} disabled={busy || isStreaming}>
              导出 Word
            </button>
          </div>
        </>
      ) : (
        <div className="empty-state">
          <strong>预览区等待内容</strong>
          <p>导入新文档后会直接生成初始预览，运行后会自动切到最新版本，也可以从历史记录打开任意轮次或修订版继续选择。</p>
        </div>
      )}
    </section>
  );
}
