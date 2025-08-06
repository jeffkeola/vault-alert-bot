namespace Core
{
    using System;
    using System.Collections.Generic;
    using System.Linq;

    using Core.Models;
    using Core.Services;

    public static class Utilities
    {
    }

    public static class ExtensionMethods
    {
        public static List<string> GetChangedPositions(HyperliquidUser user, HyperliquidSnapshot oldSnapshot, HyperliquidSnapshot newSnapshot)
        {
            var changes = new List<string>();

            // Create a dictionary of positions by Coin for easy lookup
            var oldPositionsDict = oldSnapshot.Positions?.ToDictionary(p => p.Coin, p => p, StringComparer.InvariantCultureIgnoreCase) ?? new Dictionary<string, HyperliquidPosition>();
            var newPositionsDict = newSnapshot.Positions?.ToDictionary(p => p.Coin, p => p, StringComparer.InvariantCultureIgnoreCase) ?? new Dictionary<string, HyperliquidPosition>();

            // Check for changes in size for existing coins
            foreach (var newPosition in newPositionsDict)
            {
                if (oldPositionsDict.TryGetValue(newPosition.Key, out var oldPosition))
                {
                    if (newPosition.Value.Size != oldPosition.Size)
                    {
                        var diff = newPosition.Value.Size - oldPosition.Size;
                        changes.Add($"{user.Name}: [{newPosition.Key}] | Change ({diff:#,###0.######}) | ${oldPosition.Value:#,###0.######} to ${newPosition.Value.Value:#,###0.######}");
                    }
                }
                else
                {
                    // New position added
                    changes.Add($"{user.Name}: Add | [{newPosition.Key}] | ${newPosition.Value.Value:#,###0.######}");
                }
            }

            // Check for removed positions
            foreach (var oldPosition in oldPositionsDict)
            {
                if (!newPositionsDict.ContainsKey(oldPosition.Key))
                {
                    changes.Add($"{user.Name}: Removed | [{oldPosition.Key}] | ${oldPosition.Value.Value:#,###0.######}");
                }
            }

            return changes;
        }
        public static List<string> GetChangedPositions(HyperliquidUser user, List<HyperliquidPosition> oldPositions, List<Position> newPositions)
        {
            var changes = new List<string>();

            // Create a dictionary of positions by Coin for easy lookup
            var oldPositionsDict = oldPositions.ToDictionary(p => p.Coin, p => p, StringComparer.InvariantCultureIgnoreCase) ?? new Dictionary<string, HyperliquidPosition>();
            var newPositionsDict = newPositions.ToDictionary(p => p.Coin, p => p, StringComparer.InvariantCultureIgnoreCase) ?? new Dictionary<string, Position>();

            // Check for changes in size for existing coins
            foreach (var newPosition in newPositionsDict)
            {
                if (oldPositionsDict.TryGetValue(newPosition.Key, out var oldPosition))
                {
                    if (newPosition.Value.Szi != oldPosition.Size)
                    {
                        var diff = newPosition.Value.Szi - oldPosition.Size;
                        changes.Add($"{user.Name}: [{newPosition.Key}] | Change ({diff:#,###0.######}) | ${oldPosition.Value:#,###0.######} to ${newPosition.Value.PositionValue:#,###0.######}");
                    }
                }
                else
                {
                    changes.Add($"{user.Name}: Add | [{newPosition.Key}] | ${newPosition.Value.PositionValue:#,###0.######}");
                }
            }

            // Check for removed positions
            foreach (var oldPosition in oldPositionsDict)
            {
                if (!newPositionsDict.ContainsKey(oldPosition.Key))
                {
                    changes.Add($"{user.Name}: Removed | [{oldPosition.Key}] | ${oldPosition.Value.Value:#,###0.######}");
                }
            }

            return changes;
        }
    }
}