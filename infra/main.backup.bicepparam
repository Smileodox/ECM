using './main.bicep'

// Backup deployment into a second Azure subscription.
// environment='backup' keeps all globally-unique names (OpenAI/Search/Redis/
// App Service/Storage) distinct from the primary 'poc' deployment, so the two
// can coexist. Keys are derived inside the template — no secrets needed here.
//
//   az deployment group create \
//     --resource-group rg-chatbot-backup \
//     --template-file main.bicep \
//     --parameters main.backup.bicepparam

param projectName = 'chatbot'
param location = 'westeurope'
param environment = 'backup'

// Backup runs one App Service tier above the poc (B1 → B2)
param appServicePlanSku = 'B2'

// Model list tuned to the backup subscription's quota (verified 2026-06-18,
// sub "Automotive Data Engineering Non Production - WEU", westeurope):
//   - gpt-4.1 / gpt-4.1-mini have NO GlobalStandard quota here → dropped
//   - text-embedding-3-small has no regional 'Standard' SKU → use GlobalStandard
param openaiDeployments = [
  { name: 'gpt-5.4',      model: 'gpt-5.4',      version: '2026-03-05', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.4-nano', model: 'gpt-5.4-nano', version: '2026-03-17', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5.1',      model: 'gpt-5.1',      version: '2025-11-13', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-mini',   model: 'gpt-5-mini',   version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  { name: 'gpt-5-nano',   model: 'gpt-5-nano',   version: '2025-08-07', skuName: 'GlobalStandard', capacity: 10 }
  // capacity 250: embedding throughput for bulk ingestion (cap 30 throttled hard on 15k chunks)
  { name: 'text-embedding-3-small', model: 'text-embedding-3-small', version: '1', skuName: 'GlobalStandard', capacity: 250 }
]
