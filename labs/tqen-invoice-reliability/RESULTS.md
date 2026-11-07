# TQEN invoice reliability — synthetic evaluation

Both methods read the same 40 synthetic frozen OCR extracts (20 dev, 20 holdout). The splits share no template IDs, supplier families, or normalized canonical supplier labels. The assisted policy uses a known synthetic supplier catalog spanning both splits. No OCR runs here: this measures validation policy, not OCR accuracy, production performance, or approval authority.

Reproduce from the lab directory:

```sh
python run_eval.py --fixtures fixtures/invoices_v1.json
```

For the separate controlled OCR timeout and safe retry, see the [operational runbook](RUNBOOK.md).

## Dispositions

Correct-ready and wrong-ready are READY decisions compared with the independent expected disposition. Review rate is NEEDS_REVIEW divided by all fixtures in the split.

| Split | Method | N | READY | Correct-ready | Wrong-ready | NEEDS_REVIEW | Review rate |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| overall | baseline | 40 | 40 | 16 | 24 | 0 | 0.0% |
| overall | assisted | 40 | 16 | 16 | 0 | 24 | 60.0% |
| dev | baseline | 20 | 20 | 8 | 12 | 0 | 0.0% |
| dev | assisted | 20 | 8 | 8 | 0 | 12 | 60.0% |
| holdout | baseline | 20 | 20 | 8 | 12 | 0 | 0.0% |
| holdout | assisted | 20 | 8 | 8 | 0 | 12 | 60.0% |

## Shared raw field agreement

Matches / fixtures (%), against independent labels. Missing or unparseable fields count as non-matches. Currency agreement checks the header only. Calculated line sum is numeric-only Σ(OCR quantity × OCR unit price), without checking currency consistency or applying reviewer edits.

| Split | Supplier | Currency | Stated total | Calculated line sum |
| --- | ---: | ---: | ---: | ---: |
| overall | 37/40 (92.5%) | 38/40 (95.0%) | 36/40 (90.0%) | 36/40 (90.0%) |
| dev | 19/20 (95.0%) | 19/20 (95.0%) | 18/20 (90.0%) | 17/20 (85.0%) |
| holdout | 18/20 (90.0%) | 19/20 (95.0%) | 18/20 (90.0%) | 19/20 (95.0%) |

## Date input coverage

Counts measure date presence and calendar validity, not agreement with a source date.

| Split | Valid | Missing | Invalid |
| --- | ---: | ---: | ---: |
| overall | 38 | 2 | 0 |
| dev | 19 | 1 | 0 |
| holdout | 19 | 1 | 0 |

## Invoice breakdown

| Fixture | Split / language | Failure mode | Expected | Baseline | Assisted |
| --- | --- | --- | --- | --- | --- |
| dev-01-ar-clean | dev / ar | clean | READY | READY | READY |
| dev-02-en-clean | dev / en | clean | READY | READY | READY |
| dev-03-digit-drop | dev / ar | bad_scan_digit_drop | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_LINE_TOTAL_MISMATCH`) |
| dev-04-tax-total | dev / mixed | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_TOTAL_MISMATCH`) |
| dev-05-currency-unit | dev / ar | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_CURRENCY_CONFLICT`) |
| dev-06-ar-grain-clean | dev / ar | clean | READY | READY | READY |
| dev-07-carton-clean | dev / en | clean | READY | READY | READY |
| dev-08-five-line-drop | dev / ar | bad_scan_digit_drop | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_LINE_TOTAL_MISMATCH`) |
| dev-09-ar-digit-substitution | dev / ar | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_LINE_TOTAL_MISMATCH`) |
| dev-10-ar-supplier-alias | dev / ar | similar_supplier_alias | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_SUPPLIER_AMBIGUOUS`) |
| dev-11-mixed-dairy-clean | dev / mixed | clean | READY | READY | READY |
| dev-12-kg-gram | dev / ar | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_UNIT_CONFLICT`) |
| dev-13-missing-date | dev / ar | missing_critical_field | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_MISSING_FIELD`) |
| dev-14-ar-pantry-clean | dev / ar | clean | READY | READY | READY |
| dev-15-zero-unit-price | dev / en | zero_unit_price | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_INVALID_NUMBER`) |
| dev-16-en-pantry-clean | dev / en | clean | READY | READY | READY |
| dev-17-catalog-currency | dev / en | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_CURRENCY_CONFLICT`) |
| dev-18-mixed-persian-digits-clean | dev / mixed | clean | READY | READY | READY |
| dev-19-carton-piece | dev / en | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_UNIT_CONFLICT`) |
| dev-20-cent-tax | dev / en | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_TOTAL_MISMATCH`) |
| holdout-01-ar-clean | holdout / ar | clean | READY | READY | READY |
| holdout-02-en-clean | holdout / en | clean | READY | READY | READY |
| holdout-03-supplier-alias | holdout / en | similar_supplier_alias | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_SUPPLIER_AMBIGUOUS`) |
| holdout-04-subtotal | holdout / ar | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_SUBTOTAL_MISMATCH`) |
| holdout-05-missing-total | holdout / en | missing_critical_field | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_MISSING_FIELD`) |
| holdout-06-ar-press-clean | holdout / ar | clean | READY | READY | READY |
| holdout-07-carton-clean | holdout / en | clean | READY | READY | READY |
| holdout-08-five-line-cent-tax | holdout / en | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_TOTAL_MISMATCH`) |
| holdout-09-ar-digit-substitution | holdout / ar | math_total_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_LINE_TOTAL_MISMATCH`) |
| holdout-10-ar-supplier-alias | holdout / ar | similar_supplier_alias | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_SUPPLIER_AMBIGUOUS`) |
| holdout-11-mixed-spices-clean | holdout / mixed | clean | READY | READY | READY |
| holdout-12-line-currency | holdout / en | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_CURRENCY_CONFLICT`) |
| holdout-13-missing-date | holdout / ar | missing_critical_field | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_MISSING_FIELD`) |
| holdout-14-en-chilled-clean | holdout / en | clean | READY | READY | READY |
| holdout-15-zero-unit-price | holdout / en | zero_unit_price | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_INVALID_NUMBER`) |
| holdout-16-carton-piece | holdout / en | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_UNIT_CONFLICT`) |
| holdout-17-ar-bakery-clean | holdout / ar | clean | READY | READY | READY |
| holdout-18-missing-header-currency | holdout / en | missing_critical_field | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_MISSING_FIELD`) |
| holdout-19-exact-decimal | holdout / mixed | clean | READY | READY | READY |
| holdout-20-balanced-unit | holdout / ar | currency_unit_mismatch | NEEDS_REVIEW | READY | NEEDS_REVIEW (`ERR_UNIT_CONFLICT`) |

## Reviewer walkthrough

`dev-03-digit-drop` (`SYN-D103`), line 1: frozen OCR reads quantity `٢` at unit price `٣٬٨٠٠`, with printed line total `٤٥٬٦٠٠`. The rule calculates `2 × 3800 = 7600` against `45600` and records `ERR_LINE_TOTAL_MISMATCH` at `lines[0].line_total` (`NEEDS_REVIEW`).

The scripted reviewer transcribes `١٢` from the synthetic source scenario and changes only the draft quantity. Replay yields `12 × 3800 = 45600` and `READY`. The frozen extract and scores do not change.
