using './main.bicep'

param projectName = 'chatbot'
param location = 'westeurope'
param environment = 'poc'

// Secure parameters — supply at deploy time via CLI or pipeline:
//
//   az deployment group create \
//     --resource-group rg-chatbot-poc \
//     --template-file main.bicep \
//     --parameters main.bicepparam \
//     --parameters \
//       azureOpenaiApiKey='<key from: az cognitiveservices account keys list -n oai-chatbot-poc -g rg-chatbot-poc>' \
//       azureSearchKey='<key from: az search admin-key show -n search-chatbot-poc -g rg-chatbot-poc>' \
//       redisPassword='<key from: az redis list-keys -n redis-chatbot-poc -g rg-chatbot-poc>'
//
// Or use a Key Vault reference / GitHub Actions secrets in CI/CD.
