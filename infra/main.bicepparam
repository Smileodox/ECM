using './main.bicep'

param projectName = 'chatbot'
param location = 'westeurope'
param environment = 'poc'

// The stack is self-contained: OpenAI/Search/Redis/Storage keys are read from
// the resources this template creates (listKeys), so no secrets are required
// at deploy time. Deploy with:
//
//   az deployment group create \
//     --resource-group rg-chatbot-poc \
//     --template-file main.bicep \
//     --parameters main.bicepparam
