import StudioApp from "../../components/studio-app";
import { routes, type Section } from "../../lib/studio";
import { notFound } from "next/navigation";
export default async function SectionPage({params}: {params: Promise<{section: string}>}) {
 const {section} = await params;
 if (!routes.some(route => route.id === section)) notFound();
 return <StudioApp section={section as Section} />;
}
