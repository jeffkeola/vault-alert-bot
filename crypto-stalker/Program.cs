// See https://aka.ms/new-console-template for more information

using System;
using System.Threading.Tasks;

using Core.Extensions;
using Core.Models;
using Core.Services;

using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;

HostApplicationBuilder builder = Host.CreateApplicationBuilder(args);
builder.Services.ConfigureDependencyInjection();
using IHost host = builder.Build();

await TestAsync(host.Services);

await host.RunAsync();

static async Task TestAsync(IServiceProvider hostProvider)
{
    using IServiceScope serviceScope = hostProvider.CreateScope();
    IServiceProvider provider = serviceScope.ServiceProvider;
    IHyperliquidService hyperliquidService = provider.GetRequiredService<IHyperliquidService>();

    var user = new HyperliquidUser
    {
        Id = "0xc0ee908e7bf8c8f11b039154f9f7a6230f9883f9",
        Name = "test09876"
    };

    var values = await hyperliquidService.ProcessAsync(user);

    //var response = await hyperliquidService.ProcessAsync(user);

    //Console.WriteLine($"Time: {response.Timestamp}");
    //Console.WriteLine($"Total Positions: {response.AssetPositions.Count}");

    //await hyperliquidService.CreateHyperliquidResponseAsync(response, user);

    return;
    //var user = new HyperliquidUser
    //{
    //    Id = "0x8fc7c0442e582bca195978c5a4fdec2e7c5bb0f7",
    //    Name = "Elsewhere"
    //};
    //await hyperliquidService.GetUserAsync(user.Id);
}

// string requestBody = "{\"type\": \"clearinghouseState\", \"user\": \"0x8fc7c0442e582bca195978c5a4fdec2e7c5bb0f7\"}";