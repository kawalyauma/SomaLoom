from services.extraction.evaluation import evaluate


def test_metrics_only_from_observed_reference_pairs():
    no_data = evaluate([])
    assert no_data["ocr_wer"] is None
    assert no_data["math_exact_match"] is None
    assert no_data["visual_caption_recall"] is None
    data = evaluate([{"reference_text": "the light shines", "predicted_text": "the light",
                      "reference_latex": "x^{2}", "predicted_latex": "x^{2}",
                      "reference_caption_asset_ids": ["fig1", "fig2"],
                      "predicted_caption_asset_ids": ["fig1"]}])
    assert data["ocr_wer"] == 1 / 3
    assert data["math_exact_match"] == 1
    assert data["visual_caption_recall"] == .5
