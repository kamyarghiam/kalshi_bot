import pandas as pd

from strategy.features.derived.derived_feature import AnyFeature, TimeIndependentFeature


class Addition(TimeIndependentFeature):
    def __init__(
        self, input_feat: AnyFeature, input_feat_name: str, amount: float
    ) -> None:
        self.amount = amount
        self.input_column_name = input_feat_name
        super().__init__(
            input_feats=[input_feat],
            output_feat_names=[
                self.add_feature_name(input_feat_name=input_feat_name, amount=amount)
            ],
        )

    @staticmethod
    def add_feature_name(input_feat_name: str, amount: float):
        sign = "+" if amount > 0 else ""
        return f"{input_feat_name}{sign}{amount}"

    def _apply_independent(self, all_input_data: pd.DataFrame) -> pd.DataFrame:
        to_return = self._empty_independent_return()
        to_return[self.output_feat_names[0]] = (
            all_input_data[self.input_column_name] + self.amount
        )
        return to_return
