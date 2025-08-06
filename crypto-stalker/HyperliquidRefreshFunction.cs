using System;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading.Tasks;

using Microsoft.Azure.WebJobs;
using Microsoft.Extensions.Logging;

namespace CryptoStalkerFunction
{
    public static class HyperliquidRefreshFunction
    {
        [FunctionName("RefreshFunction")]
        public static async Task Run([TimerTrigger("0 */5 * * * *")] TimerInfo myTimer, ILogger log)
        {
            log.LogInformation($"Starting RefreshFunction: {DateTime.Now}");
            try
            {
                var client = new HttpClient();
                client.BaseAddress = new Uri("https://yobofunk-cvf7d7gwg6eqhpgj.westus2-01.azurewebsites.net/");
                client.DefaultRequestHeaders.Accept.Clear();
                client.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));

                var response = await client.PostAsync("api/hyperliquid/snapshots/refresh", null);
                if (response.IsSuccessStatusCode)
                {
                    log.LogInformation($"Refresh was successful at: {DateTime.Now}");
                    return;
                }
                log.LogError("Error refreshing data");

            }
            catch (Exception ex)
            {
                log.LogError(ex, "Error running refresh");

            }
        }
    }
}