USE PosInsight;
GO

MERGE dim_gift_category_mapping AS tgt
USING (
    SELECT *
    FROM (VALUES
        ('GIFT_760_DOWN', 'GIFT_LOW', 0, 760, 1),
        ('GIFT_850_DOWN', 'GIFT_LOW', 0, 850, 1),
        ('GIFT_900_DOWN', 'GIFT_LOW', 0, 900, 1),
        ('GIFT_760_UP', 'GIFT_HIGH', 760, 5000, 2),
        ('GIFT_850_UP', 'GIFT_HIGH', 850, 5000, 2),
        ('GIFT_900_UP', 'GIFT_HIGH', 900, 5000, 2),
        ('GIFT_5000_UP', 'GIFT_LARGE', 5000, NULL, 3)
    ) AS v(source_category, canonical_group, threshold_floor, threshold_ceiling, sort_order)
) AS src
ON tgt.source_category = src.source_category
WHEN MATCHED THEN
    UPDATE SET
        canonical_group = src.canonical_group,
        threshold_floor = src.threshold_floor,
        threshold_ceiling = src.threshold_ceiling,
        sort_order = src.sort_order
WHEN NOT MATCHED THEN
    INSERT (source_category, canonical_group, threshold_floor, threshold_ceiling, sort_order)
    VALUES (src.source_category, src.canonical_group, src.threshold_floor, src.threshold_ceiling, src.sort_order);
GO
