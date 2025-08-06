namespace Core.Extensions
{
    using Core.Services;

    using Microsoft.Extensions.DependencyInjection;

    public static class AppExtensions
    {
        public static IServiceCollection ConfigureDependencyInjection(this IServiceCollection serviceCollection)
        {
            serviceCollection.AddHttpClient();
            serviceCollection.AddSingleton<IHyperliquidService, HyperliquidService>();
            serviceCollection.AddSingleton<IHyperliquidDatabaseClient, HyperliquidDatabaseClient>();
            serviceCollection.AddSingleton<ITelegramService, TelegramService>();
            return serviceCollection;
        }
    }
}