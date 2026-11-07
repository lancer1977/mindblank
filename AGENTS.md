# mindblank agent guide

<!-- devstudio-agent-policy:start schema=1 -->
## DevStudio Agent Policy

Profile: `polyhydra-standard@1`.

These instructions are generated from `.devstudio/agent-policy.yaml`.

- `authority.explicit_for_dangerous_actions` = `true`
- `collaboration.subagents` = `"bounded"`
- `communication.adhd_friendly` = `true`
- `cost.service_tier` = `"default"`
- `delivery.exact_head_review` = `true`
- `delivery.issue_first` = `true`
- `development.mfd` = `"material_changes"`
- `model_routing.luna_for_bounded_code` = `true`
- `model_routing.sol_orchestrates` = `true`
- `review.independent_for_sensitive_work` = `true`
- `verification.live_when_applicable` = `true`

<!-- devstudio-agent-policy:end -->

<!-- std:testing:start version=1 -->
## Testing standard (testing@v1)

- T1: a behavior change ships automated tests in the same PR.
- T2: a created or modified UI control (input, button, toggle, form, picker,
  interactive list, overlay widget) gets component tests: render (default and
  edge), interaction to expected event/state/call, disabled/loading/error, and
  basic accessibility (role, label).
- T3: a bug fix ships a regression test that fails before the fix.
- T4: component and unit tests are Tier 1; browser e2e is Tier 2.
- T5: issues carry a `Tests:` acceptance block and the `std:testing-v1` label.
- T6: state exemptions in the PR body as `testing-exempt: <rule> <reason>`.
- T7: keep a Tier 1 component harness for each UI framework the repo ships.
<!-- std:testing:end -->
