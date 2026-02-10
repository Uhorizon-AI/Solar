# Solar

Solar is an open-source operating framework for multi-domain AI agents, built with a Hub-and-Spoke model:

- `Sun`: your personal router and context holder.
- `Planets`: autonomous domain workspaces with their own rules.

Solar was created by [Louis Jimenez](https://github.com/louisjimenezp) and is maintained by [Uhorizon AI](https://uhorizon.ai).

## Open Source and Commercial Model

Solar is free and open source.

- Use it for personal and professional workflows.
- Contribute improvements through issues and pull requests.
- If you need implementation help, Uhorizon AI offers paid services.

Primary commercial CTA:
- Book a setup or migration call with Uhorizon AI: https://uhorizon.ai/contact

Optional support:
- Donations are optional and help sustain maintenance.
- See [`./SUPPORT.md`](./SUPPORT.md) and [`./.github/FUNDING.yml`](./.github/FUNDING.yml).

## Why Solar

A single assistant does not handle real context boundaries well. Solar separates domains by design so each domain can evolve with clear governance, memory, and execution rules.

## Architecture

```text
/Solar/
├── core/                # Versioned framework source of truth
│   ├── templates/       # Reusable templates
│   └── skills/          # Reusable skills
├── sun/                 # Local runtime workspace (gitignored)
└── planets/             # Local runtime workspace (gitignored)
```

## Quickstart

1. Clone and enter repository:
```bash
git clone git@github.com:Uhorizon-AI/Solar.git
cd Solar
```
2. Run bootstrap:
```bash
bash core/bootstrap.sh
```
3. Complete onboarding:
- [`./core/checklist-onboarding.md`](./core/checklist-onboarding.md)
- [`./core/templates/onboarding-profile.md`](./core/templates/onboarding-profile.md)

Note:
- `sun/` and `planets/` are intentionally gitignored in the framework repository.
- User runtime data should remain outside framework governance.

## How It Works

1. You request a task to the Sun.
2. The Sun routes it to the right Planet.
3. The Planet executes with domain-specific governance.
4. The Planet returns status, deliverables, and risks.

## Operating Contracts

- Request contract: [`./core/transport-contract.md`](./core/transport-contract.md)
- Report template: [`./core/report-template.md`](./core/report-template.md)
- Onboarding contract: [`./core/onboarding-conversation-contract.md`](./core/onboarding-conversation-contract.md)
- Orchestration blueprint: [`./core/orchestration-blueprint.md`](./core/orchestration-blueprint.md)
- Core governance: [`./core/AGENTS.md`](./core/AGENTS.md)

Minimum request fields:
- `objective`
- `constraints`
- `context`

Minimum response fields:
- `status`
- `deliverables`
- `risks`
- `next_steps`

## Contributing

Contributions are welcome.

1. Read [`./CONTRIBUTING.md`](./CONTRIBUTING.md).
2. Open an issue for bugs or feature proposals.
3. Submit focused pull requests.

Starter labels for first contributions:
- `good first issue`
- `help wanted`

## Security and Community

- Security reports: [`./SECURITY.md`](./SECURITY.md)
- Code of conduct: [`./CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- Support channels and response model: [`./SUPPORT.md`](./SUPPORT.md)

## Brand Usage

Use the project name as:
- Product: `Solar`
- Attribution: `Solar by Uhorizon AI`
- Optional creator attribution: `Created by @louisjimenezp` (https://github.com/louisjimenezp)

## Maintainers and Contact

- Creator: [Louis Jiménez P.](https://github.com/louisjimenezp)
- Maintainer: [Uhorizon AI](https://uhorizon.ai)
- Commercial and general inquiries: https://uhorizon.ai/contact
