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
  const canRunSelection = Boolean(activePreview && selectedCount > 0 && !busy);
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
            <button className="secondary-button" onClick={onSelectAllParagraphs} disabled={busy || !paragraphCount}>
              全选段落
            </button>
            <button className="secondary-button" onClick={onClearParagraphs} disabled={busy || !selectedCount}>
              清空选择
            </button>
            <button className="secondary-button" onClick={onCreateRevision} disabled={!canCreateRevision}>
              在当前轮生成修订版
            </button>
            <button className="primary-button" onClick={onRunNextPartial} disabled={!canRunNextPartial}>
              在下一轮处理所选段落
            </button>
          </div>
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
                    disabled={busy}
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
          </div>
          <div className="button-row">
            <button className="secondary-button" onClick={onExportTxt} disabled={busy}>
              导出 TXT
            </button>
            <button className="primary-button" onClick={onExportDocx} disabled={busy}>
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
