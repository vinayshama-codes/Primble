// Display copy for the plan cards. What Stripe actually charges lives in
// backend/config/settings.py PLANS - keep the two in step.
export const PLANS = [
  {
    id: "essentials",
    name: "Essentials",
    monthlyPrice: 199,
    annualPrice: 159,
    packageCount: "100 scores/mo",
    overage: "$2/score",
    featured: false,
    badge: null,
    cta: "Upgrade",
    features: [
      "100 scores / month",
      "Submission Quality Scoring (SQS)",
      "Cross-form validation",
      "Client-in-the-Loop™ remediation",
      "Submission brief",
      "Unlimited users",
    ],
    missing: [],
  },
  {
    id: "professional",
    name: "Professional",
    monthlyPrice: 299,
    annualPrice: 239,
    packageCount: "100 packages/mo",
    overage: "$3/package",
    featured: true,
    badge: "Most popular",
    cta: "Upgrade",
    features: [
      "100 packages / month",
      "All Essentials features",
      "ACORD forms",
      "Guided form completion",
      "Advanced client questionnaires",
      "E&O audit defense",
      "Priority support",
    ],
    missing: [],
  },
  {
    id: "enterprise",
    name: "Enterprise",
    monthlyPrice: null,
    annualPrice: null,
    packageCount: "Custom packages/mo",
    overage: "Custom",
    featured: false,
    badge: null,
    cta: "Contact sales",
    features: [
      "ACORD and Supplemental forms",
      "Custom integrations",
      "Renewal workspace",
      "Team analytics & reporting",
      "On-prem deployment",
      "Dedicated account manager",
    ],
    missing: [],
  },
];

// Largest annual discount across the priced plans, rounded to a whole percent,
// so the "Save ~N%" badge on the billing toggle can never drift from the prices.
export const ANNUAL_SAVINGS_PCT = Math.max(
  0,
  ...PLANS
    .filter((p) => p.monthlyPrice && p.annualPrice)
    .map((p) => Math.round((1 - p.annualPrice / p.monthlyPrice) * 100)),
);
