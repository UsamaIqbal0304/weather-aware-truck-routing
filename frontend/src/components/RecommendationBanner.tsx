import type { PlanResponse } from "../api/types";

interface Props {
  plan: PlanResponse;
  onShow: (routeId: string) => void;
}

/** The answer, before the evidence. The brief asks the app to recommend a
 * route, so the recommendation and the reason it won lead the panel. */
export function RecommendationBanner({ plan, onShow }: Props) {
  const { recommendation } = plan;
  const route = plan.routes.find((r) => r.id === recommendation.route_id);

  return (
    <div className={`banner${recommendation.warning ? " banner--warn" : ""}`}>
      {route ? (
        <>
          <p className="banner__title">
            Take <strong>{route.name}</strong>
          </p>
          {recommendation.reason && <p className="banner__reason">{recommendation.reason}</p>}
          <button type="button" className="button button--link" onClick={() => onShow(route.id)}>
            Show it on the map
          </button>
        </>
      ) : (
        <p className="banner__title">No route could be recommended.</p>
      )}

      {recommendation.warning && <p className="banner__warning">{recommendation.warning}</p>}

      {plan.notes.map((note) => (
        <p key={note} className="banner__note">
          {note}
        </p>
      ))}
    </div>
  );
}
