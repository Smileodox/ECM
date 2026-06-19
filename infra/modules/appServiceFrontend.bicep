@description('Name of the frontend App Service')
param name string

@description('Azure region')
param location string

@description('Resource ID of the App Service Plan')
param appServicePlanId string

@description('Linux runtime stack')
param linuxFxVersion string = 'NODE|22-lts'

@description('Backend API URL (e.g. https://app-chatbot-backend.azurewebsites.net)')
param apiUrl string

@description('Tags applied to the resource')
param tags object = {}

resource frontendApp 'Microsoft.Web/sites@2024-04-01' = {
  name: name
  location: location
  tags: tags
  kind: 'app,linux'
  properties: {
    serverFarmId: appServicePlanId
    httpsOnly: true
    siteConfig: {
      linuxFxVersion: linuxFxVersion
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      // Next.js runs as a PREBUILT standalone bundle: the deploy ships a
      // compiled `.next/standalone` payload, Azure must NOT run a build.
      // Startup runs the bundled server directly.
      appCommandLine: 'node server.js'
      appSettings: [
        // NEXT_PUBLIC_* vars are inlined at build time, so the backend URL
        // must be baked in before `npm run build` (deploy script does this).
        // Kept here for reference/visibility.
        { name: 'NEXT_PUBLIC_API_URL', value: apiUrl }
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'false' }
      ]
    }
  }
}

@description('Resource ID of the frontend App Service')
output id string = frontendApp.id

@description('Name of the frontend App Service')
output name string = frontendApp.name

@description('Default hostname of the frontend App Service')
output defaultHostName string = frontendApp.properties.defaultHostName
